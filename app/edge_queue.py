"""Cloudflare Stripe queue consumer: persist-or-retry, never silently acknowledge.

The HTTP ingress authenticates a Stripe event with a five-minute timestamp
window. Queue delivery can occur later, so the consumer verifies the signed
bytes again without enforcing that ingress-only delivery window.

A thrown exception makes Cloudflare retry the queue batch (event IDs are
unique in D1). Exhausted retries go to the configured dead-letter queue.
"""
from __future__ import annotations

from app.stripe_sig import SignatureError, parse_verified_event

# Only plans implemented in app.main are eligible for automated fulfillment.
# A missing/unknown plan is recorded for review but never provisioned.
FULFILLMENT_PLANS = frozenset({"audit", "dealdesk", "starter", "pro", "agency"})
PAID_CHECKOUT_EVENTS = frozenset({
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
})


async def process_queued_stripe_event(body: dict, env=None) -> dict:
    """Validate, durably record, then optionally schedule a paid fulfillment.

    Never returns success for missing D1, invalid payloads, or failed writes.
    """
    if not isinstance(body, dict):
        raise ValueError("invalid_queue_message")
    payload = body.get("payload") or ""
    signature = body.get("signature") or ""
    secret = getattr(env, "STRIPE_WEBHOOK_SECRET", "") if env is not None else ""
    if not secret:
        raise RuntimeError("webhook_not_configured")

    try:
        # Timestamp freshness was checked at HTTP ingress; delays/retries must
        # not invalidate a genuine, already accepted queue message.
        event = parse_verified_event(payload, signature, secret, tolerance=0)
    except (SignatureError, ValueError) as exc:
        raise ValueError("invalid_queued_stripe_signature_or_payload") from exc

    event_id = event.get("id")
    event_type = event.get("type")
    if not isinstance(event_id, str) or not event_id or not isinstance(event_type, str) or not event_type:
        raise ValueError("invalid_stripe_event")
    obj = (event.get("data") or {}).get("object") or {}
    if not isinstance(obj, dict):
        raise ValueError("invalid_stripe_event_object")
    trace_id = body.get("trace_id")

    db = getattr(env, "DB", None) if env is not None else None
    if db is None:
        # Returning without raising here previously caused irreversible queue
        # acknowledgements despite the absence of any payment journal.
        raise RuntimeError("d1_unbound")

    from app.d1 import D1Repo

    repo = D1Repo(db)
    try:
        await repo.ensure_schema()
        inserted = await repo.record_billing_event(
            event_id=event_id,
            event_type=event_type,
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            invoice_id=obj.get("invoice") or obj.get("id"),
            payload=payload,
        )

        fulfillment_queued = False
        if event_type in PAID_CHECKOUT_EVENTS:
            amount = obj.get("amount_total")
            paid = (obj.get("payment_status") == "paid"
                    and isinstance(amount, int) and not isinstance(amount, bool)
                    and amount > 0)
            metadata = obj.get("metadata") or {}
            plan = metadata.get("garcar_plan") if isinstance(metadata, dict) else None
            email = ((obj.get("customer_details") or {}).get("email")
                     or obj.get("customer_email") or "")
            session_id = obj.get("id")
            if paid and plan in FULFILLMENT_PLANS and isinstance(email, str) and email.strip() and session_id:
                # On partial failure, the event already exists; retry safely
                # creates only the missing fulfillment job.
                fulfillment_queued = await repo.enqueue_fulfillment(
                    stripe_event_id=event_id,
                    checkout_session_id=session_id,
                    plan=plan,
                    customer_email=email.lower().strip(),
                )
            else:
                print(f"[edge_queue] fulfillment withheld event_id={event_id}: unpaid_or_missing_verified_offer")

        return {
            "ok": True,
            "persisted": True,
            "inserted": inserted,
            "fulfillment_queued": fulfillment_queued,
            "event_id": event_id,
            "trace_id": trace_id,
        }
    except Exception as exc:
        # Propagate to WorkerEntrypoint.queue; Cloudflare will retry rather
        # than acknowledge an unpersisted or partially processed event.
        print(f"[edge_queue] retry_required event_id={event_id}: {type(exc).__name__}")
        raise
