import json
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_placeholder")
os.environ.setdefault("STRIPE_PRICE_STARTER", "price_starter_test")
os.environ.setdefault("STRIPE_PRICE_PRO", "price_pro_test")
os.environ.setdefault("STRIPE_PRICE_AGENCY", "price_agency_test")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "garcar-payments"


def test_pricing_returns_all_plans():
    resp = client.get("/pricing")
    assert resp.status_code == 200
    plans = {p["key"]: p["price_id"] for p in resp.json()["plans"]}
    assert plans["starter"] == "price_starter_test"
    assert plans["pro"] == "price_pro_test"
    assert plans["agency"] == "price_agency_test"


def test_pricing_excludes_plans_with_empty_price_id():
    with patch.dict(os.environ, {"STRIPE_PRICE_STARTER": ""}):
        resp = client.get("/pricing")
        assert resp.status_code == 200
        for p in resp.json()["plans"]:
            assert p["price_id"]


def test_create_checkout_session_invalid_plan():
    resp = client.post("/create-checkout-session?plan=unknown&email=buyer@example.com")
    assert resp.status_code == 400
    assert "Invalid plan" in resp.json()["detail"]


def test_create_checkout_session_success():
    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_test_abc"
    with patch("stripe.checkout.Session.create", return_value=mock_session):
        resp = client.post("/create-checkout-session?plan=starter&email=buyer@example.com")
    assert resp.status_code == 200
    assert resp.json()["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_abc"


def test_create_checkout_session_stripe_failure():
    with patch("stripe.checkout.Session.create", side_effect=Exception("card_declined")):
        resp = client.post("/create-checkout-session?plan=pro&email=buyer@example.com")
    assert resp.status_code == 500
    assert "card_declined" in resp.json()["detail"]


def _webhook_body(event_type: str, event_id: str = "evt_test") -> bytes:
    payload = {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "customer": "cus_test",
                "subscription": "sub_test",
                "invoice": "inv_test",
            }
        },
    }
    return json.dumps(payload).encode()


def _subscription_event_body(event_type: str, event_id: str, sub_id: str, plan: str = "starter", unit_amount: int = 29700) -> bytes:
    return json.dumps({
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": sub_id,
                "customer": "cus_test_001",
                "status": "active",
                "metadata": {"plan": plan},
                "items": {
                    "data": [{"price": {"id": "price_starter_test", "unit_amount": unit_amount}}]
                },
                "current_period_end": 1782285600,
            }
        },
    }).encode()


def test_webhook_invoice_paid_stored():
    body = _webhook_body("invoice.paid", "evt_inv_paid_001")
    resp = client.post("/stripe-webhook", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["received"] is True
    assert resp.json()["event_type"] == "invoice.paid"


def test_webhook_checkout_completed():
    body = _webhook_body("checkout.session.completed", "evt_checkout_001")
    resp = client.post("/stripe-webhook", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["event_type"] == "checkout.session.completed"


def test_webhook_subscription_deleted():
    body = _webhook_body("customer.subscription.deleted", "evt_sub_del_001")
    with patch("app.main.notify_slack", new_callable=AsyncMock):
        resp = client.post("/stripe-webhook", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["event_type"] == "customer.subscription.deleted"


def test_webhook_deduplicates_on_repeated_event_id():
    body = _webhook_body("invoice.payment_failed", "evt_dup_999")
    with patch("app.main.notify_slack", new_callable=AsyncMock):
        resp1 = client.post("/stripe-webhook", content=body, headers={"Content-Type": "application/json"})
        assert resp1.status_code == 200
        resp2 = client.post("/stripe-webhook", content=body, headers={"Content-Type": "application/json"})
        assert resp2.status_code == 200


def test_success_endpoint_with_session_id():
    resp = client.get("/success?session_id=cs_test_xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["session_id"] == "cs_test_xyz"


def test_success_endpoint_without_session_id():
    resp = client.get("/success")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_mrr_endpoint_returns_expected_fields():
    resp = client.get("/mrr")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_subscriptions" in data
    assert "mrr_usd" in data
    assert "subscriptions" in data
    assert isinstance(data["subscriptions"], list)


def test_webhook_subscription_created_stores_subscription():
    body = _subscription_event_body(
        "customer.subscription.created", "evt_sub_created_001", "sub_autotest_001", unit_amount=99700
    )
    resp = client.post("/stripe-webhook", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["event_type"] == "customer.subscription.created"
    mrr_resp = client.get("/mrr")
    assert mrr_resp.status_code == 200
    active_ids = {s["id"]: s for s in mrr_resp.json()["subscriptions"]}
    assert "sub_autotest_001" in active_ids
    assert active_ids["sub_autotest_001"]["mrr"] == pytest.approx(997.0)


def test_webhook_subscription_deleted_marks_cancelled_and_removes_from_mrr():
    create_body = _subscription_event_body(
        "customer.subscription.created", "evt_sub_created_002", "sub_autotest_002", unit_amount=149700
    )
    client.post("/stripe-webhook", content=create_body, headers={"Content-Type": "application/json"})

    delete_body = json.dumps({
        "id": "evt_sub_del_002",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_autotest_002",
                "customer": "cus_test_001",
                "metadata": {"plan": "starter"},
            }
        },
    }).encode()
    with patch("app.main.notify_slack", new_callable=AsyncMock):
        resp = client.post("/stripe-webhook", content=delete_body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    active_ids = {s["id"] for s in client.get("/mrr").json()["subscriptions"]}
    assert "sub_autotest_002" not in active_ids


def test_webhook_subscription_deleted_sends_churn_slack_alert():
    delete_body = json.dumps({
        "id": "evt_sub_del_slack_001",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_slack_churn_001",
                "customer": "cus_slack_001",
                "metadata": {"plan": "pro"},
            }
        },
    }).encode()
    with patch("app.main.notify_slack", new_callable=AsyncMock) as mock_notify:
        resp = client.post("/stripe-webhook", content=delete_body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    mock_notify.assert_called_once()
    assert "CHURN" in mock_notify.call_args[0][0]
    assert "sub_slack_churn_001" in mock_notify.call_args[0][0]


def test_webhook_payment_failed_sends_slack_alert():
    body = json.dumps({
        "id": "evt_pay_fail_001",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "id": "inv_fail_001",
                "customer": "cus_fail_001",
                "customer_email": "buyer@example.com",
                "amount_due": 99700,
            }
        },
    }).encode()
    with patch("app.main.notify_slack", new_callable=AsyncMock) as mock_notify:
        resp = client.post("/stripe-webhook", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    mock_notify.assert_called_once()
    alert_text = mock_notify.call_args[0][0]
    assert "PAYMENT FAILED" in alert_text
    assert "997.00" in alert_text
