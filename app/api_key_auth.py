"""Shared-secret API key check for internal read endpoints (hardening audit, Oct 2026).

Callers send the key in the ``X-API-Key`` header (or ``Authorization: Bearer <key>``).
The expected key is read from PAYMENTS_ADMIN_API_KEY on every request. If it is
missing or empty the endpoint returns 503 (fail closed): an unconfigured service
must never be open. The comparison is constant-time.
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Header, HTTPException

API_KEY_ENV = "PAYMENTS_ADMIN_API_KEY"


def require_admin_key(
    x_api_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> None:
    expected = os.getenv(API_KEY_ENV, "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail=f"Service locked: {API_KEY_ENV} is not configured")
    presented = (x_api_key or "").strip()
    if not presented and authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key",
                            headers={"WWW-Authenticate": "Bearer"})
