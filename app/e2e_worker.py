from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

import stripe
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import DownloadEntitlement, FulfillmentJob, IntegrationAction, JOB_STATUS_DEAD, JOB_STATUS_DONE, JOB_STATUS_FAILED, JOB_STATUS_PENDING, JOB_STATUS_PROCESSING, SessionLocal
from app.download import build_signed_download_url
from app.email_adapter import get_email_adapter
from app.integrations import HubSpotContact, asana_create_onboarding, hubspot_find_contact, hubspot_link_contact, linear_create_incident, notion_log_event, supabase_upsert_entitlement

logger = logging.getLogger("garcar.e2e_worker")
_OFFER_CATALOG: Optional[dict] = None


def _catalog() -> dict:
    global _OFFER_CATALOG
    if _OFFER_CATALOG is None:
        from app.main import OFFER_CATALOG
        _OFFER_CATALOG = OFFER_CATALOG
    return _OFFER_CATALOG


def _backoff(attempt: int) -> float:
    return min(10 * (2 ** max(attempt - 1, 0)), 300)


def _claim(db: Session, job: FulfillmentJob) -> bool:
    result = db.execute(update(FulfillmentJob).where(FulfillmentJob.id == job.id, FulfillmentJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_FAILED])).values(status=JOB_STATUS_PROCESSING, attempts=FulfillmentJob.attempts + 1, updated_at=datetime.utcnow()))
    db.commit()
    return result.rowcount == 1


def _action(db: Session, job_id: int, stage: str) -> IntegrationAction:
    row = db.query(IntegrationAction).filter_by(job_id=job_id, stage=stage).one_or_none()
    if row:
        return row
    try:
        row = IntegrationAction(job_id=job_id, stage=stage)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        return db.query(IntegrationAction).filter_by(job_id=job_id, stage=stage).one()


def _stage(db: Session, job: FulfillmentJob, name: str, fn):
    action = _action(db, job.id, name)
    if action.status == "completed":
        # Every completed stage must be resumable without issuing another
        # external write. HubSpot returns a typed contact; other stages persist
        # a stable provider identifier in external_id.
        if name == "hubspot_match" and action.external_id:
            return HubSpotContact(action.external_id, job.customer_email)
        return action.external_id
    try:
        result = fn()
        external_id = None
        if isinstance(result, str):
            external_id = result
        elif isinstance(result, HubSpotContact):
            external_id = result.id
        elif isinstance(result, dict):
            external_id = result.get("id") or result.get("project_id") or result.get("task_id")
        elif isinstance(result, list) and result and isinstance(result[0], dict):
            external_id = result[0].get("id")
        action.status = "completed"
        action.attempts += 1
        action.external_id = str(external_id) if external_id else action.external_id
        action.last_error = None
        action.updated_at = datetime.utcnow()
        db.commit()
        return result
    except Exception as exc:
        action.status = "failed"
        action.attempts += 1
        action.last_error = str(exc)[:2000]
        action.updated_at = datetime.utcnow()
        db.commit()
        job.failed_stage = name
        raise


def process_job(db: Session, job: FulfillmentJob) -> None:
    stage = "stripe_verification"
    try:
        session = stripe.checkout.Session.retrieve(job.checkout_session_id)
        if session.payment_status not in ("paid", "no_payment_required"):
            raise ValueError(f"payment_status={session.payment_status!r} is not paid")
        customer_id = session.get("customer") or ""
        email = ((session.get("customer_details") or {}).get("email") or session.get("customer_email") or job.customer_email or "").strip().lower()
        if not customer_id or not email:
            raise ValueError("Stripe checkout is missing customer ID or email")
        if job.plan not in _catalog():
            raise ValueError(f"Unknown plan: {job.plan!r}")
        job.stripe_customer_id = customer_id
        job.customer_email = email
        db.commit()

        stage = "hubspot_match"
        contact = _stage(db, job, stage, lambda: hubspot_find_contact(customer_id, email))
        if isinstance(contact, str) and job.hubspot_contact_id:
            contact = HubSpotContact(job.hubspot_contact_id, email)
        if not isinstance(contact, HubSpotContact):
            raise ValueError(f"No HubSpot contact found for Stripe customer {customer_id} or {email}")
        job.hubspot_contact_id = contact.id
        db.commit()
        _stage(db, job, "hubspot_link", lambda: hubspot_link_contact(contact.id, customer_id))

        stage = "supabase_entitlement"
        entitlement = _stage(db, job, stage, lambda: supabase_upsert_entitlement(stripe_event_id=job.stripe_event_id, checkout_session_id=job.checkout_session_id or "", stripe_customer_id=customer_id, hubspot_contact_id=contact.id, plan=job.plan or "", email=email))
        if isinstance(entitlement, list) and entitlement:
            job.supabase_entitlement_id = str(entitlement[0].get("id", ""))
        elif isinstance(entitlement, str) and not job.supabase_entitlement_id:
            job.supabase_entitlement_id = entitlement
        db.commit()

        stage = "asana_onboarding"
        asana = _stage(db, job, stage, lambda: asana_create_onboarding(checkout_session_id=job.checkout_session_id or "", customer_email=email, plan=job.plan or ""))
        if isinstance(asana, dict):
            job.asana_project_id = str(asana.get("project_id", ""))
            job.asana_task_id = str(asana.get("task_id", ""))
        elif isinstance(asana, str) and not job.asana_project_id:
            job.asana_project_id = asana
        db.commit()

        stage = "notion_audit"
        notion = _stage(db, job, stage, lambda: notion_log_event(event_id=job.stripe_event_id, checkout_session_id=job.checkout_session_id or "", stripe_customer_id=customer_id, hubspot_contact_id=contact.id, plan=job.plan or ""))
        if isinstance(notion, dict):
            job.notion_event_id = str(notion.get("id", ""))
        elif isinstance(notion, str) and not job.notion_event_id:
            job.notion_event_id = notion
        db.commit()

        stage = "download_entitlement"
        action = _action(db, job.id, stage)
        if action.status != "completed":
            existing = db.query(DownloadEntitlement).filter_by(stripe_event_id=job.stripe_event_id).one_or_none()
            if not existing:
                db.add(DownloadEntitlement(stripe_event_id=job.stripe_event_id, customer_email=email, plan=job.plan or ""))
                db.commit()
            action.status = "completed"
            action.attempts += 1
            db.commit()

        stage = "email_delivery"
        if not job.email_sent:
            action = _action(db, job.id, stage)
            if action.status != "completed":
                url = build_signed_download_url(plan=job.plan or "", email=email, event_id=job.stripe_event_id)
                offer = _catalog()[job.plan]
                get_email_adapter().send_download_link(to=email, product_name=offer.get("name", job.plan), download_url=url)
                job.email_sent = True
                action.status = "completed"
                action.attempts += 1
                db.commit()

        job.failed_stage = None
        job.status = JOB_STATUS_DONE
        job.completed_at = datetime.utcnow()
        job.last_error = None
        db.commit()
    except Exception as exc:
        job.failed_stage = stage
        job.last_error = str(exc)[:4000]
        job.status = JOB_STATUS_DEAD if job.attempts >= FulfillmentJob.MAX_ATTEMPTS else JOB_STATUS_FAILED
        db.commit()
        try:
            incident = linear_create_incident(correlation_id=job.stripe_event_id, failed_stage=stage, error=str(exc), attempts=job.attempts)
            if incident:
                job.linear_issue_id = incident
                db.commit()
        except Exception:
            logger.exception("linear incident creation failed for %s", job.stripe_event_id)
        logger.exception("checkout orchestration failed event=%s stage=%s", job.stripe_event_id, stage)


def run_once(max_jobs: int = 25) -> int:
    db = SessionLocal()
    count = 0
    try:
        jobs = db.query(FulfillmentJob).filter(FulfillmentJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_FAILED])).order_by(FulfillmentJob.created_at).limit(max_jobs).all()
        for job in jobs:
            if job.attempts and job.updated_at and (datetime.utcnow() - job.updated_at).total_seconds() < _backoff(job.attempts):
                continue
            if not _claim(db, job):
                continue
            db.refresh(job)
            process_job(db, job)
            count += 1
    finally:
        db.close()
    return count


async def worker_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("e2e worker loop failure")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
