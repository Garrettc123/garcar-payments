"""Offline dispatcher regression tests. No external SDK calls are made."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class PaymentDispatchTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "integrations" / "stripe_handler.py"
        tree = ast.parse(path.read_text())
        names = {"handle_stripe_webhook", "_on_checkout_complete"}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.provider = Mock()
        self.ns = {"stripe": self.provider,
            "Config": SimpleNamespace(STRIPE_WEBHOOK_SECRET="offline-fixture-secret"),
            "CHECKOUT_EVENTS": {"checkout.session.completed", "checkout.session.async_payment_succeeded"}}
        for name in ("provision_tenant", "close_deal", "create_onboarding_project",
                     "create_client_workspace", "send_contract", "fulfill_order",
                     "_on_subscription_renewed", "_on_subscription_cancelled", "_on_refund"):
            self.ns[name] = Mock()
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), self.ns)
        self.session = {"id": "cs_offline", "status": "complete", "payment_status": "paid",
            "customer_details": {"email": "test@example.invalid"}, "amount_total": 1000}

    def dispatch(self, event_type="checkout.session.completed"):
        self.provider.Webhook.construct_event.return_value = {"type": event_type,
            "data": {"object": self.session}}
        return self.ns["handle_stripe_webhook"](b"offline-fixture", "offline-signature")

    def test_paid_checkout_activates(self):
        self.assertEqual(self.dispatch()["status"], "processed")
        self.ns["provision_tenant"].assert_called_once()

    def test_delayed_payment_activates(self):
        self.dispatch("checkout.session.async_payment_succeeded")
        self.ns["provision_tenant"].assert_called_once()

    def test_unpaid_does_not_activate(self):
        for status in ("unpaid", "no_payment_required", None):
            self.session["payment_status"] = status
            self.assertEqual(self.dispatch()["status"], "skipped")
        self.ns["provision_tenant"].assert_not_called()
        self.ns["send_contract"].assert_not_called()

    def test_incomplete_does_not_activate(self):
        self.session["status"] = "open"
        self.assertEqual(self.dispatch()["status"], "skipped")
        self.ns["provision_tenant"].assert_not_called()

    def test_missing_email_blocks_all_side_effects(self):
        self.session["customer_details"] = None
        with self.assertRaises(ValueError):
            self.dispatch()
        self.ns["provision_tenant"].assert_not_called()

    def test_missing_session_id_blocks_all_side_effects(self):
        self.session.pop("id")
        with self.assertRaises(ValueError):
            self.dispatch()
        self.ns["provision_tenant"].assert_not_called()

    def test_unconfigured_secret_fails_closed(self):
        self.ns["Config"].STRIPE_WEBHOOK_SECRET = " "
        with self.assertRaises(RuntimeError):
            self.dispatch()
        self.provider.Webhook.construct_event.assert_not_called()

    def test_unknown_event_is_ignored(self):
        self.assertEqual(self.dispatch("checkout.session.async_payment_failed")["status"], "ignored")
        self.ns["provision_tenant"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
