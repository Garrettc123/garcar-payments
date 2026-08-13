"""
Signed download URL utilities for garcar-payments.

URLs are HMAC-signed with a short-lived expiry so that:
- Only the server can issue valid links.
- Links expire after a configurable TTL (default 24 h).
- The entitlement (email + plan) is verified before a link is issued.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional


_SIGNATURE_VERSION = "v1"
_DEFAULT_TTL_SECONDS = 86_400  # 24 hours


def _signing_secret() -> str:
    from app.settings import get_settings  # noqa: PLC0415

    s = get_settings()
    secret = s.download_signing_secret
    if not secret:
        # Insecure fallback for local development only — never used in production
        # because assert_production_ready() exits if this is empty.
        secret = "dev-insecure-signing-secret"
    return secret


def _sign(payload: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_signed_download_url(
    plan: str,
    email: str,
    event_id: str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """Return an absolute signed download URL for the given entitlement."""
    from app.settings import get_settings  # noqa: PLC0415

    expires = int(time.time()) + ttl_seconds
    payload = f"{_SIGNATURE_VERSION}:{plan}:{email}:{event_id}:{expires}"
    sig = _sign(payload, _signing_secret())
    base_url = get_settings().app_base_url.rstrip("/")
    return (
        f"{base_url}/download"
        f"?plan={plan}&email={email}&event_id={event_id}"
        f"&expires={expires}&sig={sig}&sv={_SIGNATURE_VERSION}"
    )


def verify_download_token(
    plan: str,
    email: str,
    event_id: str,
    expires: int,
    sig: str,
    sv: str = _SIGNATURE_VERSION,
) -> bool:
    """
    Verify the download token.  Returns False if:
    - The signature version is unknown.
    - The HMAC does not match (constant-time compare).
    - The link has expired.
    """
    if sv != _SIGNATURE_VERSION:
        return False
    if time.time() > expires:
        return False
    payload = f"{sv}:{plan}:{email}:{event_id}:{expires}"
    expected = _sign(payload, _signing_secret())
    return hmac.compare_digest(expected, sig)
