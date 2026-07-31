"""
Tests for garcar-payments app endpoints.
Stripe API calls are mocked so tests run without real credentials.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

# Use the lifespan context so init_db() runs before tests
@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ── /health ────────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "garcar-payments"
    assert "configured_offers" in data


def test_health_lists_configured_offers(client):
    response = client.get("/health")
    offers = response.json()["configured_offers"]
    # Default price IDs are embedded, so all plans are configured
    assert "audit" in offers
    assert "dealdesk" in offers


# ── /pricing ───────────────────────────────────────────────────────────────

def test_pricing_returns_all_plans(client):
    response = client.get("/pricing")
    assert response.status_code == 200
    plans = {p["key"]: p for p in response.json()["plans"]}
    assert set(plans.keys()) == {"audit", "dealdesk", "starter", "pro", "agency"}


def test_pricing_audit_is_configured(client):
    response = client.get("/pricing")
    plans = {p["key"]: p for p in response.json()["plans"]}
    assert plans["audit"]["configured"] is True


def test_pricing_dealdesk_is_configured(client):
    response = client.get("/pricing")
    plans = {p["key"]: p for p in response.json()["plans"]}
    assert plans["dealdesk"]["configured"] is True


# ── /create-checkout-session ───────────────────────────────────────────────

def _mock_stripe_session(plan: str = "audit", mode: str = "payment") -> MagicMock:
    session = MagicMock()
    session.url = f"https://checkout.stripe.com/pay/test_{plan}"
    return session


def test_create_checkout_session_returns_url(client):
    with patch("stripe.checkout.Session.create", return_value=_mock_stripe_session()):
        response = client.post(
            "/create-checkout-session",
            json={"plan": "audit", "email": "test@example.com", "source": "unit-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "checkout_url" in data
    assert data["checkout_url"].startswith("https://checkout.stripe.com/")
    assert data["plan"] == "audit"
    assert data["mode"] == "payment"


def test_create_checkout_session_subscription_plan(client):
    with patch("stripe.checkout.Session.create", return_value=_mock_stripe_session("starter", "subscription")):
        response = client.post(
            "/create-checkout-session",
            json={"plan": "starter", "email": "user@example.com"},
        )
    assert response.status_code == 200
    assert response.json()["mode"] == "subscription"


def test_create_checkout_session_invalid_plan(client):
    response = client.post(
        "/create-checkout-session",
        json={"plan": "nonexistent", "email": "test@example.com"},
    )
    assert response.status_code == 400


def test_create_checkout_session_missing_email(client):
    response = client.post(
        "/create-checkout-session",
        json={"plan": "audit", "email": ""},
    )
    assert response.status_code == 400


def test_create_checkout_session_invalid_email(client):
    response = client.post(
        "/create-checkout-session",
        json={"plan": "audit", "email": "notanemail"},
    )
    assert response.status_code == 400


# ── /stripe-webhook ────────────────────────────────────────────────────────

_SAMPLE_EVENT = {
    "id": "evt_test_001",
    "type": "checkout.session.completed",
    "livemode": False,
    "data": {
        "object": {
            "id": "cs_test_001",
            "customer": "cus_test",
            "amount_total": 19700,
            "currency": "usd",
            "customer_details": {"email": "buyer@example.com"},
        }
    },
}


def test_webhook_persists_event(client):
    """Webhook endpoint accepts a valid event and returns received=True."""
    payload = json.dumps(_SAMPLE_EVENT).encode()
    response = client.post(
        "/stripe-webhook",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert data["event_type"] == "checkout.session.completed"


def test_webhook_deduplicates_events(client):
    """Sending the same event twice must not raise — duplicate is silently dropped."""
    event = {**_SAMPLE_EVENT, "id": "evt_dedup_test"}
    payload = json.dumps(event).encode()
    headers = {"content-type": "application/json"}

    r1 = client.post("/stripe-webhook", content=payload, headers=headers)
    r2 = client.post("/stripe-webhook", content=payload, headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200  # not 500 — duplicate is absorbed


def test_webhook_rejects_invalid_signature(client):
    """When STRIPE_WEBHOOK_SECRET is set, an invalid signature must return 400."""
    import os
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_secret"
    try:
        payload = json.dumps(_SAMPLE_EVENT).encode()
        response = client.post(
            "/stripe-webhook",
            content=payload,
            headers={
                "content-type": "application/json",
                "stripe-signature": "v1=invalidsig,t=1234567890",
            },
        )
        assert response.status_code == 400
    finally:
        del os.environ["STRIPE_WEBHOOK_SECRET"]


# ── /success ───────────────────────────────────────────────────────────────

def test_success_page(client):
    response = client.get("/success?session_id=cs_test_123")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["session_id"] == "cs_test_123"

