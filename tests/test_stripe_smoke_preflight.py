"""Contract tests for the actual Stripe test-fixture preflight shell."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stripe-smoke-preflight.sh"


def run_guard(key=None, event="payment_intent.succeeded"):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if key is not None:
        env["STRIPE_TEST_SECRET_KEY"] = key
    if event is not None:
        env["STRIPE_EVENT"] = event
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=5, check=False
    )


class TestStripeSmokePreflight(unittest.TestCase):
    def test_accepts_explicit_test_key_for_approved_events(self):
        for event in ("payment_intent.succeeded", "checkout.session.completed"):
            result = run_guard("sk_test_local_fixture", event)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("test-mode credential", result.stdout)

    def test_rejects_missing_credentials(self):
        self.assertNotEqual(run_guard().returncode, 0)

    def test_rejects_live_secret_and_live_restricted_key(self):
        for value in ("sk_live_private_fixture", "rk_live_private_fixture", "rk_test_local_fixture", "pk_test_local_fixture"):
            result = run_guard(value)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(value, result.stdout + result.stderr)

    def test_rejects_unsupported_or_injected_events(self):
        for event in ("", "invoice.paid", "payment_intent.succeeded; echo unsafe", None):
            result = run_guard("sk_test_local_fixture", event)
            self.assertNotEqual(result.returncode, 0)

    def test_never_logs_provided_secret(self):
        key = "sk_test_private_fixture_string"
        r = run_guard(key)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn(key, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
