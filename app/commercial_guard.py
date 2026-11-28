"""Fail-closed commercial controls for the existing Garcar Payments service.

This module never initiates charges, outreach or fulfillment. It validates
the conditions under which the existing Stripe adapter may enqueue a job.
The worker must separately retrieve the Checkout Session from Stripe.
"""
from __future__ import annotations

from urllib.parse import urlsplit

PAID_EVENTS = frozenset(("checkout.session.completed", "checkout.session.async_payment_succeeded"))


class CommercialGuardError(ValueError):
    """A requested commercial action failed validation."""


def _same_origin(base: str, candidate: str) -> bool:
    try:
        a, b = urlsplit(base), urlsplit(candidate)
        return bool(
            a.scheme in ("http", "https") and a.hostname
            and a.username is None and a.password is None
            and b.username is None and b.password is None
            and b.scheme == a.scheme and b.hostname == a.hostname
            and b.port == a.port and b.netloc == a.netloc
            and b.path.startswith("/") and not b.path.startswith("//")
            and not b.fragment and chr(92) not in candidate
            and chr(10) not in candidate and chr(13) not in candidate
        )
    except ValueError:
        return False


def checkout_redirects(base_url: str, success_url: str | None, cancel_url: str | None) -> tuple[str, str]:
    """Reject third-party or ambiguous checkout redirects."""
    base = base_url.rstrip("/")
    if not urlsplit(base).hostname:
        raise CommercialGuardError("APP_BASE_URL must be absolute")
    success = success_url or base + "/success?session_id={CHECKOUT_SESSION_ID}"
    cancel = cancel_url or base + "/pricing"
    if not all(_same_origin(base, x) for x in (success, cancel)):
        raise CommercialGuardError("Checkout redirect must use the configured application origin")
    return success, cancel


def is_paid_checkout_event(event_type: str, obj: object) -> bool:
    """The event must have a paid Checkout Session; signature verified upstream.

    A signed event is not itself proof of final settlement; Stripe API
    retrieval by the durable worker remains mandatory.
    """
    return bool(
        event_type in PAID_EVENTS
        and isinstance(obj, dict)
        and isinstance(obj.get("id"), str)
        and obj["id"].startswith("cs_")
        and obj.get("payment_status") == "paid"
        and isinstance(obj.get("metadata"), dict)
        and isinstance(obj["metadata"].get("garcar_plan"), str)
        and obj["metadata"]["garcar_plan"].strip()
    )


def validate_fulfillment_session(
    session: object, expected_session_id: str, expected_plan: str, allowed_plans: dict
) -> None:
    """Validate the session retrieved through Stripe before granting delivery."""
    if not isinstance(expected_session_id, str) or not expected_session_id.startswith("cs_"):
        raise CommercialGuardError("invalid checkout session identifier")
    if not isinstance(expected_plan, str) or expected_plan not in allowed_plans:
        raise CommercialGuardError("offer plan not on allow-list")

    def field(key: str):
        return session.get(key) if isinstance(session, dict) else getattr(session, key, None)

    if field("id") != expected_session_id:
        raise CommercialGuardError("checkout session mismatch")
    if field("payment_status") != "paid":
        raise CommercialGuardError("checkout is not paid")
    metadata = field("metadata")
    plan = metadata.get("garcar_plan") if isinstance(metadata, dict) else getattr(metadata, "garcar_plan", None)
    if plan != expected_plan:
        raise CommercialGuardError("checkout plan does not match the job")
    if field("livemode") not in (True, False):
        raise CommercialGuardError("payment mode is unspecified")


def observed_event_evidence(event: dict) -> dict:
    """A signed webhook observation must never be labeled reconciled revenue."""
    if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not isinstance(event.get("type"), str):
        raise CommercialGuardError("invalid Stripe event")
    return {
        "stripe_event_id": event["id"],
        "stripe_event_type": event["type"],
        "livemode": event.get("livemode") is True,
        "evidence_kind": "signed_event_observed",
        "payment_reconciled": False,
        "fulfillment_verified": False,
        "revenue_eligible": False,
    }
