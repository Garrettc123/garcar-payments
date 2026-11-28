"""Offline contract tests for the payment-to-fulfillment release gates."""
import unittest
from types import SimpleNamespace

from app.commercial_guard import (
    CommercialGuardError,
    checkout_redirects,
    is_paid_checkout_event,
    observed_event_evidence,
    validate_fulfillment_session,
)

BASE = "https://payments.garcar.com"
SESSION = "cs_test_proof_1"
PLAN = "dealdesk"
CATALOG = {PLAN: {"name": "Lead Review"}}


def paid(**overrides):
    x = {
        "id": SESSION, "payment_status": "paid",
        "metadata": {"garcar_plan": PLAN}, "livemode": False,
    }
    x.update(overrides)
    return x


class CommercialGuardTests(unittest.TestCase):
    def test_default_redirects_are_local(self):
        success, cancel = checkout_redirects(BASE, None, None)
        self.assertTrue(success.startswith(BASE + "/success"))
        self.assertEqual(cancel, BASE + "/pricing")

    def test_explicit_same_origin_redirects(self):
        self.assertEqual(checkout_redirects(BASE, BASE + "/done", BASE + "/back"),
                         (BASE + "/done", BASE + "/back"))

    def test_external_redirects_blocked(self):
        bad = (
            "https://evil.example/steal",
            "https://payments.garcar.com.evil.example/done",
            "https://payments.garcar.com@evil.example/done",
            "http://payments.garcar.com/done",
            "//evil.example/",
            "https://payments.garcar.com:443/done",
            "https://payments.garcar.com/done#fragment",
        )
        for url in bad:
            with self.subTest(url=url), self.assertRaises(CommercialGuardError):
                checkout_redirects(BASE, url, None)

    def test_bad_origin_config_blocked(self):
        with self.assertRaises(CommercialGuardError):
            checkout_redirects("relative", None, None)

    def test_only_paid_signed_checkout_candidate_enqueued(self):
        self.assertTrue(is_paid_checkout_event("checkout.session.completed", paid()))
        self.assertTrue(is_paid_checkout_event("checkout.session.async_payment_succeeded", paid()))

    def test_unpaid_and_incomplete_events_do_not_enqueue(self):
        cases = [
            ("checkout.session.completed", paid(payment_status="unpaid")),
            ("checkout.session.completed", paid(payment_status="no_payment_required")),
            ("checkout.session.completed", paid(metadata={})),
            ("checkout.session.completed", paid(id="wrong")),
            ("checkout.session.async_payment_failed", paid()),
            ("invoice.paid", paid()),
            ("checkout.session.completed", None),
        ]
        for kind, obj in cases:
            with self.subTest(kind=kind, obj=obj):
                self.assertFalse(is_paid_checkout_event(kind, obj))

    def test_verified_session_dict_and_object(self):
        validate_fulfillment_session(paid(), SESSION, PLAN, CATALOG)
        validate_fulfillment_session(SimpleNamespace(**paid()), SESSION, PLAN, CATALOG)

    def test_unpaid_mismatched_and_unknown_plans_block_delivery(self):
        cases = [
            (paid(id="cs_test_other"), SESSION, PLAN, CATALOG),
            (paid(payment_status="unpaid"), SESSION, PLAN, CATALOG),
            (paid(payment_status="no_payment_required"), SESSION, PLAN, CATALOG),
            (paid(metadata={"garcar_plan": "starter"}), SESSION, PLAN, CATALOG),
            (paid(livemode=None), SESSION, PLAN, CATALOG),
            (paid(), "other", PLAN, CATALOG),
            (paid(), SESSION, "unknown", CATALOG),
            (paid(), SESSION, PLAN, {}),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(CommercialGuardError):
                validate_fulfillment_session(*args)

    def test_signed_observation_not_reconciled_payment(self):
        data = observed_event_evidence({
            "id": "evt_proof_1", "type": "checkout.session.completed", "livemode": True
        })
        self.assertEqual(data["evidence_kind"], "signed_event_observed")
        self.assertTrue(data["livemode"])
        self.assertFalse(data["payment_reconciled"])
        self.assertFalse(data["fulfillment_verified"])
        self.assertFalse(data["revenue_eligible"])

    def test_malformed_evidence_rejected(self):
        with self.assertRaises(CommercialGuardError):
            observed_event_evidence({"id": "evt_only"})

if __name__ == "__main__":
    unittest.main()
