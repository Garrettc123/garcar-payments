from __future__ import annotations

import stripe
from sqlalchemy.exc import IntegrityError

from app.db import BillingEvent, FulfillmentJob, SessionLocal, JOB_STATUS_PENDING, JOB_STATUS_FAILED
from app.e2e_worker import _claim, process_job
from app.settings import get_settings


def process_queued_stripe_event(body: dict) -> None:
    payload = body.get("payload", "")
    signature = body.get("signature", "")
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is required for queue processing")
    event = stripe.Webhook.construct_event(payload.encode("utf-8"), signature, secret)
    event_id = event.get("id")
    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {}) or {}
    if not event_id:
        raise ValueError("Stripe event has no ID")

    db = SessionLocal()
    try:
        try:
            db.add(BillingEvent(event_id=event_id, event_type=event_type or "unknown", customer_id=obj.get("customer"), subscription_id=obj.get("subscription"), invoice_id=obj.get("invoice") or obj.get("id"), payload=payload))
            db.commit()
        except IntegrityError:
            db.rollback()

        if event_type != "checkout.session.completed":
            return
        if obj.get("payment_status") != "paid" and obj.get("status") != "complete":
            return

        metadata = obj.get("metadata") or {}
        plan = metadata.get("garcar_plan", "")
        session_id = obj.get("id", "")
        job = db.query(FulfillmentJob).filter_by(stripe_event_id=event_id).one_or_none()
        if job is None and session_id:
            job = db.query(FulfillmentJob).filter_by(checkout_session_id=session_id).one_or_none()
        if job is None:
            job = FulfillmentJob(
                stripe_event_id=event_id,
                checkout_session_id=session_id,
                stripe_customer_id=obj.get("customer", ""),
                plan=plan,
                customer_email=((obj.get("customer_details") or {}).get("email") or obj.get("customer_email") or "").lower().strip(),
            )
            db.add(job)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                job = db.query(FulfillmentJob).filter_by(checkout_session_id=session_id).one()
            else:
                db.refresh(job)

        # The same claim path is used by the local supervisor and the edge
        # queue, preventing two workers from executing external stages at once.
        if job.status not in (JOB_STATUS_PENDING, JOB_STATUS_FAILED):
            return
        if not _claim(db, job):
            return
        db.refresh(job)
        process_job(db, job)
    finally:
        db.close()
