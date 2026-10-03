"""Test helpers for the hardening audit (Oct 2026): sign webhook bodies like Stripe does.

The values here are dummies for tests only, never real secrets.
"""
from __future__ import annotations

import hashlib
import hmac
import time

TEST_WEBHOOK_SECRET = "whsec_unit_test_dummy_not_real"
TEST_ADMIN_API_KEY = "unit-test-admin-key-not-real"
ADMIN_HEADERS = {"X-API-Key": TEST_ADMIN_API_KEY}


def signed_headers(payload: bytes, secret: str = TEST_WEBHOOK_SECRET, extra: dict | None = None) -> dict:
    ts = int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "stripe-signature": f"t={ts},v1={mac}"}
    headers.update(extra or {})
    return headers
