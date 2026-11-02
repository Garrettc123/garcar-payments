import os
import tempfile

# Shared test environment. Must run before any test module imports app.*:
# several test files used os.environ.setdefault() at import time, so whichever
# file was collected first decided the config for the whole run (order-dependent
# failures). A file-backed SQLite DB is used because ":memory:" is per-thread and
# FastAPI's TestClient runs the app on a different thread than the test.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="garcar_payments_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR}/test.db"
for _k, _v in {
    # Split so secret scanners do not flag a dummy value as a live-format Stripe key.
    "STRIPE_SECRET_KEY": "sk_" + "test_placeholder",
    "STRIPE_PRICE_STARTER": "price_starter_test",
    "STRIPE_PRICE_PRO": "price_pro_test",
    "STRIPE_PRICE_AGENCY": "price_agency_test",
    "STRIPE_PRICE_MARS_STARTER": "price_mars_starter_test",
    "STRIPE_PRICE_MARS_PROFESSIONAL": "price_mars_pro_test",
}.items():
    os.environ.setdefault(_k, _v)

import pytest

from tests.stripe_test_utils import TEST_ADMIN_API_KEY, TEST_WEBHOOK_SECRET


@pytest.fixture(autouse=True)
def _hardening_env(monkeypatch):
    """Hardening audit (Oct 2026): the webhook and admin endpoints fail closed without
    these, so every test starts with dummy values set. Tests that check the
    fail-closed path delete them with monkeypatch."""
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("PAYMENTS_ADMIN_API_KEY", TEST_ADMIN_API_KEY)


@pytest.fixture(scope="session", autouse=True)
def _app_started():
    """Run the real app lifespan once (creates tables, loads the offer catalog), so tests
    that use a bare TestClient(app) see the same state as a running server."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app):
        yield
