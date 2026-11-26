"""Regression tests for Cloudflare payment queue safety.

Events, signatures, DB, and delivery are isolated fixtures. These tests do
not contact Stripe or process an actual customer payment.
"""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app.edge_queue import process_queued_stripe_event
from app.stripe_sig import compute_signature, SignatureError, parse_verified_event

SECRET = "whsec_regression_only"


class Journal:
    def __init__(self):
        self.events = set()
        self.jobs = set()
        self.fail_event_write = False
        self.fail_job_write = False

    async def ensure_schema(self):
        return None

    async def record_billing_event(self, **kwargs):
        if self.fail_event_write:
            raise RuntimeError("D1 down")
        event_id = kwargs["event_id"]
        new = event_id not in self.events
        self.events.add(event_id)
        return new

    async def enqueue_fulfillment(self, **kwargs):
        if self.fail_job_write:
            raise RuntimeError("D1 fulfillment down")
        event_id = kwargs["stripe_event_id"]
        new = event_id not in self.jobs
        self.jobs.add(event_id)
        return new


def message(
    *, event_id="evt_paid", event_type="checkout.session.completed",
    payment_status="paid", amount_total=49700, plan="dealdesk",
    ts=None, secret=SECRET,
):
    obj = {
        "id": "cs_regression",
        "payment_status": payment_status,
        "amount_total": amount_total,
        "metadata": {"garcar_plan": plan} if plan is not None else {},
        "customer_details": {"email": "buyer@example.test"},
    }
    event = {"id": event_id, "type": event_type, "livemode": True,
             "data": {"object": obj}}
    payload = json.dumps(event)
    ts = int(time.time()) if ts is None else ts
    header = f"t={ts},v1={compute_signature(ts, payload, secret)}"
    return {"payload": payload, "signature": header, "event_id": event_id}


@pytest.fixture(autouse=True)
def patch_repo(monkeypatch):
    # Keep the queue consumer exactly the same, replace only D1 I/O.
    monkeypatch.setattr("app.d1.D1Repo", lambda db: db)


def run(msg, journal=None, secret=SECRET):
    env = SimpleNamespace(STRIPE_WEBHOOK_SECRET=secret, DB=journal)
    return asyncio.run(process_queued_stripe_event(msg, env))


def test_missing_d1_raises_so_queue_retries():
    with pytest.raises(RuntimeError, match="d1_unbound"):
        run(message())


def test_missing_secret_raises_so_queue_retries():
    with pytest.raises(RuntimeError, match="webhook_not_configured"):
        run(message(), Journal(), secret="")


def test_tampered_payload_rejected():
    signed = message()
    signed["payload"] = signed["payload"].replace("49700", "99900")
    with pytest.raises(ValueError, match="invalid_queued"):
        run(signed, Journal())


def test_unpaid_checkout_is_recorded_not_fulfilled():
    journal = Journal()
    result = run(message(payment_status="unpaid"), journal)
    assert result["persisted"] is True
    assert result["fulfillment_queued"] is False
    assert journal.events == {"evt_paid"}
    assert journal.jobs == set()


@pytest.mark.parametrize("amount", [0, -1, None, True])
def test_nonpositive_or_invalid_amount_never_fulfills(amount):
    journal = Journal()
    result = run(message(amount_total=amount), journal)
    assert result["persisted"] is True
    assert result["fulfillment_queued"] is False
    assert not journal.jobs


@pytest.mark.parametrize("plan", [None, "not-a-real-plan"])
def test_missing_or_unknown_plan_does_not_fulfill(plan):
    journal = Journal()
    result = run(message(plan=plan), journal)
    assert result["persisted"] is True
    assert result["fulfillment_queued"] is False
    assert not journal.jobs


def test_paid_checkout_records_once_and_enqueues_once():
    journal = Journal()
    first = run(message(), journal)
    second = run(message(), journal)
    assert first["inserted"] is True
    assert first["fulfillment_queued"] is True
    assert second["inserted"] is False
    assert second["fulfillment_queued"] is False
    assert journal.events == journal.jobs == {"evt_paid"}


def test_async_payment_succeeded_enqueues_only_after_paid():
    journal = Journal()
    result = run(message(event_id="evt_async", event_type="checkout.session.async_payment_succeeded"), journal)
    assert result["fulfillment_queued"] is True
    assert journal.jobs == {"evt_async"}


def test_event_write_error_propagates():
    journal = Journal()
    journal.fail_event_write = True
    with pytest.raises(RuntimeError, match="D1 down"):
        run(message(), journal)


def test_partial_write_failure_can_be_retried_idempotently():
    journal = Journal()
    journal.fail_job_write = True
    with pytest.raises(RuntimeError, match="D1 fulfillment down"):
        run(message(), journal)
    assert journal.events == {"evt_paid"}
    assert journal.jobs == set()
    journal.fail_job_write = False
    retry = run(message(), journal)
    assert retry["persisted"] is True
    assert retry["inserted"] is False
    assert retry["fulfillment_queued"] is True
    assert journal.jobs == {"evt_paid"}


def test_delayed_queue_delivery_keeps_signature_valid():
    # HTTP ingress must check freshness; the queue may retry much later.
    old = int(time.time()) - 900
    msg = message(ts=old)
    with pytest.raises(SignatureError):
        parse_verified_event(msg["payload"], msg["signature"], SECRET)
    journal = Journal()
    result = run(msg, journal)
    assert result["persisted"] is True


def test_unrecognized_events_are_journaled_only():
    journal = Journal()
    result = run(message(event_id="evt_fail", event_type="invoice.payment_failed"), journal)
    assert result["persisted"] is True
    assert not journal.jobs
