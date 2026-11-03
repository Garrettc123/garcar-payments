import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.stripe_test_utils import ADMIN_HEADERS, signed_headers

client = TestClient(app)


def _sub_event(event_id, sub_id, amount, interval="month", etype="customer.subscription.created"):
    return json.dumps({
        "id": event_id,
        "type": etype,
        "data": {"object": {
            "id": sub_id,
            "customer": "cus_sub_test",
            "status": "active",
            "metadata": {"plan": "pro"},
            "items": {"data": [{"price": {
                "id": "price_x", "unit_amount": amount, "currency": "usd",
                "recurring": {"interval": interval},
            }}]},
        }},
    }).encode()


def _post(body):
    return client.post("/stripe-webhook", content=body, headers=signed_headers(body))


def _mrr_by_id():
    return {s["id"]: s["mrr"] for s in client.get("/mrr", headers=ADMIN_HEADERS).json()["subscriptions"]}


def test_annual_plan_is_normalized_to_monthly():
    assert _post(_sub_event("evt_annual_1", "sub_annual_1", 120000, interval="year")).status_code == 200
    assert _mrr_by_id()["sub_annual_1"] == pytest.approx(100.0)


def test_subscription_update_changes_mrr():
    _post(_sub_event("evt_upd_1", "sub_upd_1", 50000))
    _post(_sub_event("evt_upd_2", "sub_upd_1", 80000, etype="customer.subscription.updated"))
    assert _mrr_by_id()["sub_upd_1"] == pytest.approx(800.0)


def test_duplicate_delivery_does_not_resend_slack_alert():
    body = json.dumps({
        "id": "evt_dup_alert_1",
        "type": "invoice.payment_failed",
        "data": {"object": {"id": "inv_dup_1", "customer": "cus_d", "customer_email": "a@b.co", "amount_due": 5000}},
    }).encode()
    with patch("app.main.notify_slack", new_callable=AsyncMock) as notify:
        assert _post(body).status_code == 200
        assert _post(body).status_code == 200  # Stripe retry of the same event
    notify.assert_called_once()
