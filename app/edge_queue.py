"""Edge queue consumer. Pyodide-safe.

Re-verifies HMAC with stdlib. Writes D1 when env.DB exists.
Does not import stripe, SQLAlchemy, or e2e_worker.
"""
from __future__ import annotations

from app.stripe_sig import SignatureError, parse_verified_event


async def process_queued_stripe_event(body: dict, env=None) -> dict:
    payload = body.get("payload") or ""
    signature = body.get("signature") or ""
    secret = ""
    if env is not None:
        secret = getattr(env, "STRIPE_WEBHOOK_SECRET", "") or ""
    if not secret:
        print("[edge_queue] missing STRIPE_WEBHOOK_SECRET; ack without persist")
        return {"ok": False, "reason": "webhook_not_configured"}
    try:
        event = parse_verified_event(payload, signature, secret)
    except SignatureError:
        print("[edge_queue] invalid signature on queued payload")
        return {"ok": False, "reason": "invalid_signature"}
    except ValueError:
        print("[edge_queue] malformed queued payload")
        return {"ok": False, "reason": "malformed_payload"}

    event_id = event.get("id") or body.get("event_id")
    event_type = event.get("type") or body.get("event_type")
    obj = (event.get("data") or {}).get("object") or {}
    trace_id = body.get("trace_id")
    print(
        f"[edge_queue] accepted event_id={event_id} type={event_type} trace={trace_id}"
    )

    db = getattr(env, "DB", None) if env is not None else None
    if db is None:
        return {
            "ok": True,
            "persisted": False,
            "reason": "d1_unbound",
            "event_id": event_id,
            "trace_id": trace_id,
        }

    from app.d1 import D1Repo

    repo = D1Repo(db)
    try:
        await repo.ensure_schema()
        inserted = await repo.record_billing_event(
            event_id=event_id,
            event_type=event_type or "unknown",
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            invoice_id=obj.get("invoice") or obj.get("id"),
            payload=payload,
        )
        if event_type == "checkout.session.completed":
            email = (
                ((obj.get("customer_details") or {}).get("email"))
                or obj.get("customer_email")
                or ""
            )
            plan = (obj.get("metadata") or {}).get("garcar_plan") or ""
            await repo.enqueue_fulfillment(
                stripe_event_id=event_id,
                checkout_session_id=obj.get("id"),
                plan=plan,
                customer_email=str(email).lower().strip(),
            )
        return {
            "ok": True,
            "persisted": True,
            "inserted": inserted,
            "event_id": event_id,
            "trace_id": trace_id,
        }
    except Exception as exc:
        print(f"[edge_queue] d1_failed {type(exc).__name__}")
        return {"ok": False, "reason": "d1_failed", "event_id": event_id}
