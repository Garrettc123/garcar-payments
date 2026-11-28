"""HTTP-level release regression tests: no live provider calls."""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app, OFFER_CATALOG
from tests.stripe_test_utils import signed_headers

client = TestClient(app)


def event(event_id: str, status: str = "paid", metadata=None) -> bytes:
    return json.dumps({
        "id": event_id,
        "type": "checkout.session.completed",
        "livemode": False,
        "data": {"object": {
            "id": "cs_test_review_" + event_id,
            "payment_status": status,
            "metadata": metadata if metadata is not None else {"garcar_plan": "dealdesk"},
            "customer_details": {"email": "reviewer@example.test"},
        }}
    }).encode()


def test_signed_paid_checkout_calls_durable_enqueue_once():
    payload = event("evt_gate_paid")
    with patch.dict(OFFER_CATALOG, {"dealdesk": {"name": "Review", "price_id": "price_test", "mode": "payment"}}), \
         patch("app.main._enqueue_fulfillment") as enqueue, \
         patch("app.main._append_gc_ledger"):
        res = client.post("/stripe-webhook", content=payload, headers=signed_headers(payload))
    assert res.status_code == 200
    enqueue.assert_called_once()


def test_signed_unpaid_checkout_never_calls_enqueue():
    payload = event("evt_gate_unpaid", "unpaid")
    with patch("app.main._enqueue_fulfillment") as enqueue, \
         patch("app.main._append_gc_ledger"):
        res = client.post("/stripe-webhook", content=payload, headers=signed_headers(payload))
    assert res.status_code == 200
    enqueue.assert_not_called()


def test_signed_missing_offer_metadata_never_enqueues():
    payload = event("evt_gate_missing_plan", "paid", {})
    with patch("app.main._enqueue_fulfillment") as enqueue, \
         patch("app.main._append_gc_ledger"):
        res = client.post("/stripe-webhook", content=payload, headers=signed_headers(payload))
    assert res.status_code == 200
    enqueue.assert_not_called()


def test_untrusted_checkout_redirect_rejected_without_stripe_call():
    with patch.dict(OFFER_CATALOG, {"dealdesk": {
        "name": "Review", "price_id": "price_test", "mode": "payment"
    }}), patch("stripe.checkout.Session.create") as stripe_create:
        res = client.post("/create-checkout-session", json={
            "plan": "dealdesk",
            "email": "buyer@example.test",
            "success_url": "https://attacker.example/checkout"
        })
    assert res.status_code == 400
    stripe_create.assert_not_called()


def test_invalid_signature_still_rejected():
    payload = event("evt_gate_bad_signature")
    res = client.post("/stripe-webhook", content=payload,
                      headers=signed_headers(payload, secret="whsec_wrong"))
    assert res.status_code == 400
