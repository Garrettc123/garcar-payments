import pytest

from tests.stripe_test_utils import TEST_ADMIN_API_KEY, TEST_WEBHOOK_SECRET


@pytest.fixture(autouse=True)
def _hardening_env(monkeypatch):
    """Hardening audit (Oct 2026): the webhook and admin endpoints fail closed without
    these, so every test starts with dummy values set. Tests that check the
    fail-closed path delete them with monkeypatch."""
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("PAYMENTS_ADMIN_API_KEY", TEST_ADMIN_API_KEY)
