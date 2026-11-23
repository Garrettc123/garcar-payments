"""The FastAPI fallback must never fulfill unpaid or unidentified checkouts."""
from app.main import _enqueue_fulfillment
from app.db import SessionLocal, FulfillmentJob


def _count(event_id: str) -> int:
    db = SessionLocal()
    try:
        return db.query(FulfillmentJob).filter_by(stripe_event_id=event_id).count()
    finally:
        db.close()


def _object(payment_status="paid", amount=49700, plan="dealdesk", email="buyer@example.test"):
    return {
        "id": "cs_fallback_regression",
        "payment_status": payment_status,
        "amount_total": amount,
        "metadata": {"garcar_plan": plan} if plan is not None else {},
        "customer_details": {"email": email},
    }


def test_fastapi_unpaid_checkout_never_enqueues():
    event_id = "evt_fallback_unpaid_regression"
    _enqueue_fulfillment({"id": event_id}, _object(payment_status="unpaid"))
    assert _count(event_id) == 0


def test_fastapi_missing_plan_never_enqueues():
    event_id = "evt_fallback_no_plan_regression"
    _enqueue_fulfillment({"id": event_id}, _object(plan=None))
    assert _count(event_id) == 0


def test_fastapi_zero_amount_never_enqueues():
    event_id = "evt_fallback_zero_regression"
    _enqueue_fulfillment({"id": event_id}, _object(amount=0))
    assert _count(event_id) == 0


def test_fastapi_missing_buyer_never_enqueues():
    event_id = "evt_fallback_no_email_regression"
    _enqueue_fulfillment({"id": event_id}, _object(email=""))
    assert _count(event_id) == 0


def test_fastapi_paid_checkout_queues_idempotently():
    event_id = "evt_fallback_paid_regression"
    try:
        _enqueue_fulfillment({"id": event_id}, _object())
        _enqueue_fulfillment({"id": event_id}, _object())
        assert _count(event_id) == 1
    finally:
        # Avoid sharing fixture state with other tests.
        db = SessionLocal()
        try:
            db.query(FulfillmentJob).filter_by(stripe_event_id=event_id).delete()
            db.commit()
        finally:
            db.close()
