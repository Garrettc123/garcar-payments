"""Hardening audit (Oct 2026): webhook and admin endpoints must fail closed.

- POST /stripe-webhook returns 503 when STRIPE_WEBHOOK_SECRET is unset/empty/blank,
  400 when the signature is missing or wrong, and 200 only for a correctly signed body.
- GET /mrr (app) and GET /events (legacy root app) need PAYMENTS_ADMIN_API_KEY:
  503 when it is not configured, 401 for a missing/wrong key, 200 with the right key.
All values are dummies.
"""
import json
import os
import types

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from tests.stripe_test_utils import ADMIN_HEADERS, TEST_ADMIN_API_KEY, signed_headers


@pytest.fixture(scope="module")
def client():
    with TestClient(app_main.app) as c:
        yield c


def _body(event_id):
    return json.dumps({"id": event_id, "type": "ping.test", "data": {"object": {}}}).encode()


@pytest.fixture
def no_settings_secret(monkeypatch):
    # Make sure a cached Settings object (or a local .env) can't supply the secret.
    monkeypatch.setattr(app_main, "get_settings",
                        lambda: types.SimpleNamespace(stripe_webhook_secret=""), raising=False)


# ── Stripe webhook ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, "", "   "])
def test_webhook_503_when_secret_missing(client, monkeypatch, no_settings_secret, value):
    if value is None:
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    else:
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", value)
    payload = _body("evt_fc_unset")
    # Even a "signed" request and a plain unsigned JSON body are refused.
    assert client.post("/stripe-webhook", content=payload, headers=signed_headers(payload)).status_code == 503
    assert client.post("/stripe-webhook", content=payload,
                       headers={"Content-Type": "application/json"}).status_code == 503


def test_webhook_400_when_signature_missing(client):
    payload = _body("evt_fc_nosig")
    r = client.post("/stripe-webhook", content=payload, headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_webhook_400_when_signature_wrong(client):
    payload = _body("evt_fc_badsig")
    r = client.post("/stripe-webhook", content=payload,
                    headers=signed_headers(payload, secret="whsec_wrong_dummy"))
    assert r.status_code == 400


def test_webhook_400_when_body_tampered(client):
    payload = _body("evt_fc_tamper")
    headers = signed_headers(payload)
    r = client.post("/stripe-webhook", content=_body("evt_fc_tamper_other"), headers=headers)
    assert r.status_code == 400


def test_webhook_200_when_signed(client):
    payload = _body("evt_fc_ok_001")
    r = client.post("/stripe-webhook", content=payload, headers=signed_headers(payload))
    assert r.status_code == 200
    assert r.json()["received"] is True


# ── /mrr (app) ─────────────────────────────────────────────────────────────

def test_mrr_503_when_key_not_configured(client, monkeypatch):
    monkeypatch.delenv("PAYMENTS_ADMIN_API_KEY", raising=False)
    assert client.get("/mrr", headers=ADMIN_HEADERS).status_code == 503
    monkeypatch.setenv("PAYMENTS_ADMIN_API_KEY", "  ")
    assert client.get("/mrr", headers=ADMIN_HEADERS).status_code == 503


def test_mrr_401_without_or_with_wrong_key(client):
    assert client.get("/mrr").status_code == 401
    assert client.get("/mrr", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/mrr", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_mrr_200_with_key(client):
    assert client.get("/mrr", headers=ADMIN_HEADERS).status_code == 200
    assert client.get("/mrr", headers={"Authorization": f"Bearer {TEST_ADMIN_API_KEY}"}).status_code == 200


# ── /events and /webhooks/stripe (legacy root main.py) ─────────────────────

@pytest.fixture
def root_client(monkeypatch):
    # integrations/config.py reads these with os.environ[...] at import time.
    import re
    from pathlib import Path
    cfg = (Path(__file__).resolve().parents[1] / "integrations" / "config.py").read_text()
    for name in set(re.findall(r'os\.environ\["([A-Z0-9_]+)"\]', cfg)) - {"STRIPE_WEBHOOK_SECRET"}:
        if not os.environ.get(name):
            monkeypatch.setenv(name, "dummy_for_import")
    import main as root_main
    return TestClient(root_main.app)


def test_root_events_requires_key(root_client, monkeypatch):
    assert root_client.get("/events").status_code == 401
    assert root_client.get("/events", headers={"X-API-Key": "wrong"}).status_code == 401
    assert root_client.get("/events", headers=ADMIN_HEADERS).status_code == 200
    monkeypatch.delenv("PAYMENTS_ADMIN_API_KEY", raising=False)
    assert root_client.get("/events", headers=ADMIN_HEADERS).status_code == 503


def test_root_webhook_503_when_secret_empty(root_client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "")
    r = root_client.post("/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})
    assert r.status_code == 503


# ── backend/payments.py (secondary copy, mounted at /payments by backend/main.py) ──

@pytest.fixture
def backend_client():
    from backend.payments import app as backend_app
    return TestClient(backend_app)


@pytest.mark.parametrize("value", [None, "", "whsec_REPLACE_ME"])
def test_backend_webhook_503_without_real_secret(backend_client, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    else:
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", value)
    payload = _body("evt_backend_unset")
    r = backend_client.post("/webhook/stripe", content=payload, headers=signed_headers(payload, secret=value or "x"))
    assert r.status_code == 503


def test_backend_webhook_400_bad_signature(backend_client):
    payload = _body("evt_backend_bad")
    assert backend_client.post("/webhook/stripe", content=payload).status_code == 400
    r = backend_client.post("/webhook/stripe", content=payload,
                            headers=signed_headers(payload, secret="whsec_wrong_dummy"))
    assert r.status_code == 400


def test_backend_mrr_requires_key(backend_client, monkeypatch):
    assert backend_client.get("/mrr").status_code == 401
    monkeypatch.delenv("PAYMENTS_ADMIN_API_KEY", raising=False)
    assert backend_client.get("/mrr", headers=ADMIN_HEADERS).status_code == 503
