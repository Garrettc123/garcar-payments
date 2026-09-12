"""Stripe webhook HMAC — stdlib only. Safe on Pyodide.

Matches stripe.Webhook.construct_event verify_header:
signed_payload = f"{t}.{raw_body}"
HMAC-SHA256(key=whsec_... utf-8, msg=signed_payload) hex vs header v1.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

DEFAULT_TOLERANCE = 300


class SignatureError(ValueError):
    pass


def _parse_header(header: str) -> tuple[int, list[str]]:
    timestamp = None
    signatures: list[str] = []
    for item in header.split(","):
        parts = item.split("=", 1)
        if len(parts) != 2:
            continue
        k, v = parts[0].strip(), parts[1].strip()
        if k == "t" and timestamp is None:
            try:
                timestamp = int(v)
            except ValueError:
                continue
        elif k == "v1":
            signatures.append(v)
    if timestamp is None or not signatures:
        raise SignatureError("malformed Stripe-Signature header")
    return timestamp, signatures


def compute_signature(timestamp: int, payload: str, secret: str) -> str:
    signed = f"{timestamp}.{payload}"
    return hmac.new(secret.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_header(payload: str, header: str, secret: str, tolerance: int = DEFAULT_TOLERANCE) -> int:
    if not secret:
        raise SignatureError("missing webhook secret")
    if not header:
        raise SignatureError("missing Stripe-Signature header")
    timestamp, signatures = _parse_header(header)
    expected = compute_signature(timestamp, payload, secret)
    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise SignatureError("no matching v1 signature")
    if tolerance and timestamp < time.time() - tolerance:
        raise SignatureError("timestamp outside tolerance")
    return timestamp


def parse_verified_event(payload: str, header: str, secret: str) -> dict:
    verify_header(payload, header, secret)
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed payload") from exc
    if not isinstance(event, dict):
        raise ValueError("malformed payload")
    return event
