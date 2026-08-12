"""
Fulfillment worker for garcar-payments.

Processes ``FulfillmentJob`` rows that are in ``pending`` status:
1. Retrieves the Checkout Session server-side from Stripe to confirm payment.
2. Verifies the plan is in the product allow-list.
3. Records a ``DownloadEntitlement`` (idempotent).
4. Sends a signed download link via the email adapter.
5. Marks the job ``done``.

Retries up to FulfillmentJob.MAX_ATTEMPTS times with exponential back-off.
Exhausted jobs are moved to ``dead`` status for manual review.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Optional

import stripe
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import (
    DownloadEntitlement,
    FulfillmentJob,
    JOB_STATUS_DEAD,
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_PROCESSING,
    SessionLocal,
)
from app.download import build_signed_download_url
from app.email_adapter import get_email_adapter

logger = logging.getLogger("garcar.worker")

# Offer allow-list imported lazily to avoid circular imports
_OFFER_CATALOG: Optional[dict] = None


def _get_offer_catalog() -> dict:
    global _OFFER_CATALOG
    if _OFFER_CATALOG is None:
        from app.main import OFFER_CATALOG  # noqa: PLC0415

        _OFFER_CATALOG = OFFER_CATALOG
    return _OFFER_CATALOG


def _backoff_seconds(attempt: int) -> float:
    """Exponential back-off: 10s, 20s, 40s, 80s, 160s …"""
    return min(10 * (2 ** attempt), 300)


def process_one(db: Session, job: FulfillmentJob) -> None:
    """
    Process a single fulfillment job.  Mutates ``job`` in place and commits.
    """
    job.status = JOB_STATUS_PROCESSING
    job.attempts += 1
    job.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        # ── 1. Verify payment with Stripe ────────────────────────────────
        session = stripe.checkout.Session.retrieve(job.checkout_session_id)
        if session.payment_status not in ("paid", "no_payment_required"):
            raise ValueError(
                f"Session {job.checkout_session_id} payment_status={session.payment_status!r} — not paid"
            )

        # ── 2. Verify plan is in the product allow-list ──────────────────
        catalog = _get_offer_catalog()
        if job.plan not in catalog:
            raise ValueError(f"Plan {job.plan!r} is not in the product allow-list")

        # ── 3. Record entitlement (idempotent) ────────────────────────────
        try:
            entitlement = DownloadEntitlement(
                stripe_event_id=job.stripe_event_id,
                customer_email=job.customer_email or "",
                plan=job.plan or "",
            )
            db.add(entitlement)
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.info("Entitlement already exists for event %s", job.stripe_event_id)

        # ── 4. Send download link email (once) ────────────────────────────
        if not job.email_sent and job.customer_email:
            url = build_signed_download_url(
                plan=job.plan or "",
                email=job.customer_email,
                event_id=job.stripe_event_id,
            )
            offer = catalog.get(job.plan, {})
            get_email_adapter().send_download_link(
                to=job.customer_email,
                product_name=offer.get("name", job.plan or "product"),
                download_url=url,
            )
            job.email_sent = True

        # ── 5. Mark done ──────────────────────────────────────────────────
        job.status = JOB_STATUS_DONE
        job.completed_at = datetime.now(timezone.utc)
        job.last_error = None

    except Exception as exc:
        logger.exception("Fulfillment job %s failed (attempt %d)", job.id, job.attempts)
        job.last_error = str(exc)[:2000]
        if job.attempts >= FulfillmentJob.MAX_ATTEMPTS:
            job.status = JOB_STATUS_DEAD
            logger.error(
                "Fulfillment job %s moved to dead-letter after %d attempts",
                job.id,
                job.attempts,
            )
        else:
            job.status = JOB_STATUS_FAILED

    job.updated_at = datetime.now(timezone.utc)
    db.commit()


def run_pending(max_jobs: int = 50) -> int:
    """
    Pull up to ``max_jobs`` pending/failed jobs and process them.
    Returns the number of jobs processed.
    """
    db = SessionLocal()
    processed = 0
    try:
        jobs = (
            db.query(FulfillmentJob)
            .filter(FulfillmentJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_FAILED]))
            .order_by(FulfillmentJob.created_at)
            .limit(max_jobs)
            .all()
        )
        for job in jobs:
            if job.attempts > 0:
                delay = _backoff_seconds(job.attempts - 1)
                elapsed = (
                    datetime.now(timezone.utc)
                    - (job.updated_at or job.created_at).replace(tzinfo=timezone.utc)
                ).total_seconds()
                if elapsed < delay:
                    logger.debug(
                        "Job %s back-off: waiting %.0fs (elapsed %.0fs)",
                        job.id,
                        delay,
                        elapsed,
                    )
                    continue
            process_one(db, job)
            processed += 1
    finally:
        db.close()

    return processed
