"""Serverless billing must fail closed when storage cannot persist events.

No network calls, Stripe sessions, or real credentials are used.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as payments


@pytest.mark.parametrize(
    "database_url",
    ["", "sqlite:////tmp/garcar_payments.db", "sqlite:///:memory:"],
)
def test_vercel_rejects_non_durable_billing_storage(monkeypatch, database_url):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    if database_url:
        monkeypatch.setenv("DATABASE_URL", database_url)
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)

    assert payments._serverless_durable_database_missing() is True
    with TestClient(payments.app) as client:
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert "Durable PostgreSQL" in str(ready.json())

        checkout = client.post(
            "/create-checkout-session",
            json={"plan": "starter", "email": "test@example.invalid"},
        )
        assert checkout.status_code == 503

        webhook = client.post("/stripe-webhook", content=b"{}")
        assert webhook.status_code == 503


def test_serverless_postgres_configuration_passes_preflight(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://name:nonsecret@localhost:5432/localtest"
    )
    # This only checks URL configuration, not database connectivity.
    assert payments._serverless_durable_database_missing() is False


def test_non_serverless_local_dev_is_not_blocked(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    assert payments._serverless_durable_database_missing() is False
