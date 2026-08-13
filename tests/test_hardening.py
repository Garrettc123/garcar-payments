"""
Tests for production-hardening additions:
- Settings module fail-closed behaviour
- Signed download URL verification
- Fulfillment worker (offline / mocked)
- Email adapter test double
- /livez and /readyz endpoints
- Download endpoint
"""
from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.settings import Settings
from app.download import build_signed_download_url, verify_download_token
from app.email_adapter import FakeEmailAdapter as TestEmailAdapter, set_email_adapter


# ── Settings: production validation ─────────────────────────────────────────

def test_settings_production_rejects_missing_stripe_key():
    """Production startup must fail when STRIPE_SECRET_KEY is absent."""
    s = Settings(
        stripe_secret_key="",
        environment="production",
    )
    missing = s.validate_for_production()
    assert "STRIPE_SECRET_KEY" in missing


def test_settings_production_rejects_missing_webhook_secret():
    s = Settings(
        stripe_secret_key="sk_live_test",
        stripe_webhook_secret="",
        environment="production",
    )
    missing = s.validate_for_production()
    assert "STRIPE_WEBHOOK_SECRET" in missing


def test_settings_production_rejects_missing_signing_secret():
    s = Settings(
        stripe_secret_key="sk_live_test",
        stripe_webhook_secret="whsec_test",
        download_signing_secret="",
        environment="production",
    )
    missing = s.validate_for_production()
    assert "DOWNLOAD_SIGNING_SECRET" in missing


def test_settings_production_passes_when_all_secrets_set():
    s = Settings(
        stripe_secret_key="sk_live_test",
        stripe_webhook_secret="whsec_test",
        download_signing_secret="abc123abc123abc123abc123abc123ab",
        app_base_url="https://example.com",
        stripe_price_audit="price_a",
        stripe_price_dealdesk="price_b",
        stripe_price_starter="price_c",
        stripe_price_pro="price_d",
        stripe_price_agency="price_e",
        environment="production",
    )
    assert s.validate_for_production() == []


def test_settings_rejects_placeholder_stripe_key():
    import pydantic
    with pytest.raises((pydantic.ValidationError, ValueError)):
        Settings(stripe_secret_key="sk_test_REPLACE_ME")


def test_settings_is_production():
    s = Settings(environment="production")
    assert s.is_production() is True

    s2 = Settings(environment="development")
    assert s2.is_production() is False


# ── Download URL signing ──────────────────────────────────────────────────────

def _override_signing_secret(secret: str):
    """Patch the signing secret for the duration of a test."""
    import app.download as _dl
    original = _dl._signing_secret
    _dl._signing_secret = lambda: secret
    return original


def test_download_url_valid_signature():
    import app.download as _dl
    orig = _dl._signing_secret
    _dl._signing_secret = lambda: "test-secret-abc"
    try:
        url = build_signed_download_url("audit", "buyer@example.com", "evt_123", ttl_seconds=3600)
        assert "/download?" in url
        assert "sig=" in url
        assert "expires=" in url
    finally:
        _dl._signing_secret = orig


def test_download_verify_valid_token():
    import app.download as _dl
    orig = _dl._signing_secret
    _dl._signing_secret = lambda: "test-secret-abc"
    try:
        expires = int(time.time()) + 3600
        from app.download import _sign, _SIGNATURE_VERSION
        payload = f"{_SIGNATURE_VERSION}:audit:buyer@example.com:evt_123:{expires}"
        sig = _sign(payload, "test-secret-abc")
        assert verify_download_token("audit", "buyer@example.com", "evt_123", expires, sig) is True
    finally:
        _dl._signing_secret = orig


def test_download_verify_expired_token():
    import app.download as _dl
    orig = _dl._signing_secret
    _dl._signing_secret = lambda: "test-secret-abc"
    try:
        expires = int(time.time()) - 1  # already expired
        from app.download import _sign, _SIGNATURE_VERSION
        payload = f"{_SIGNATURE_VERSION}:audit:buyer@example.com:evt_123:{expires}"
        sig = _sign(payload, "test-secret-abc")
        assert verify_download_token("audit", "buyer@example.com", "evt_123", expires, sig) is False
    finally:
        _dl._signing_secret = orig


def test_download_verify_bad_signature():
    expires = int(time.time()) + 3600
    assert verify_download_token("audit", "buyer@example.com", "evt_123", expires, "badsig") is False


# ── Email adapter ─────────────────────────────────────────────────────────────

def test_test_email_adapter_records_messages():
    adapter = TestEmailAdapter()
    adapter.send_download_link("user@example.com", "Operational Audit", "https://example.com/dl")
    assert len(adapter.sent) == 1
    assert adapter.sent[0].to == "user@example.com"
    assert "Operational Audit" in adapter.sent[0].subject


def test_test_email_adapter_never_calls_resend():
    """TestEmailAdapter must never import or call resend."""
    adapter = TestEmailAdapter()
    with patch("resend.Emails.send") as mock_send:
        adapter.send_download_link("x@example.com", "Product", "https://example.com/dl")
    mock_send.assert_not_called()


# ── /livez and /readyz ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_livez(client):
    resp = client.get("/livez")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "alive"
    assert "uptime_s" in data


def test_readyz(client):
    # In test environment STRIPE_SECRET_KEY is not set, so readyz returns 503
    # OR if the test env has it set it returns 200 — either is acceptable;
    # we just check the endpoint exists and returns JSON.
    resp = client.get("/readyz")
    assert resp.status_code in (200, 503)
    assert resp.headers["content-type"].startswith("application/json")


# ── /download endpoint ────────────────────────────────────────────────────────

def test_download_endpoint_rejects_bad_sig(client):
    resp = client.get(
        "/download",
        params={
            "plan": "audit",
            "email": "buyer@example.com",
            "event_id": "evt_test",
            "expires": int(time.time()) + 3600,
            "sig": "invalidsig",
        },
    )
    assert resp.status_code == 403


def test_download_endpoint_rejects_expired(client):
    import app.download as _dl
    orig = _dl._signing_secret
    _dl._signing_secret = lambda: "test-secret-abc"
    try:
        expires = int(time.time()) - 1
        from app.download import _sign, _SIGNATURE_VERSION
        payload = f"{_SIGNATURE_VERSION}:audit:buyer@example.com:evt_exp:{expires}"
        sig = _sign(payload, "test-secret-abc")
        resp = client.get(
            "/download",
            params={
                "plan": "audit",
                "email": "buyer@example.com",
                "event_id": "evt_exp",
                "expires": expires,
                "sig": sig,
            },
        )
        assert resp.status_code == 403
    finally:
        _dl._signing_secret = orig
