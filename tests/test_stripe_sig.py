import json
import time

from app.stripe_sig import SignatureError, compute_signature, parse_verified_event, verify_header

SECRET = "whsec_test_secret"


def _header(payload: str, secret: str = SECRET, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    return f"t={ts},v1={compute_signature(ts, payload, secret)}"


def test_valid_signature_parses_event():
    payload = json.dumps({"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {}}})
    event = parse_verified_event(payload, _header(payload), SECRET)
    assert event["id"] == "evt_1"


def test_wrong_secret_aborts():
    payload = "{}"
    try:
        verify_header(payload, _header(payload), "whsec_other")
        assert False, "should have raised"
    except SignatureError:
        pass


def test_stale_timestamp_aborts():
    payload = "{}"
    old = int(time.time()) - 301
    try:
        verify_header(payload, _header(payload, ts=old), SECRET)
        assert False, "should have raised"
    except SignatureError as exc:
        assert "tolerance" in str(exc)
