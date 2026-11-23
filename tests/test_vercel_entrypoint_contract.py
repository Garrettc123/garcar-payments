"""Fail-closed Vercel entrypoint/Payments API contract regression tests.

These tests never call Stripe, invoke a webhook, or launch a fulfillment worker.
They verify that the declared Vercel application exposes the documented routes.
"""
from importlib import import_module
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_ROUTES = {
    ("GET", "/livez"),
    ("GET", "/readyz"),
    ("GET", "/health"),
    ("GET", "/pricing"),
    ("POST", "/create-checkout-session"),
    ("POST", "/stripe-webhook"),
    ("GET", "/download"),
    ("GET", "/mrr"),
}


def test_vercel_entrypoint_is_primary_payments_api():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entrypoint = config["tool"]["vercel"]["entrypoint"]
    assert entrypoint == "app.main:app", (
        "Vercel must expose the Payments API, not the separate MARS subscription "
        "showcase which lacks the Stripe webhook and readiness contract."
    )


def test_vercel_application_exposes_payments_contract():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    module_name, symbol = config["tool"]["vercel"]["entrypoint"].split(":", 1)
    module = import_module(module_name)
    api = getattr(module, symbol)
    actual_routes = {
        (method, route.path)
        for route in api.routes
        for method in (getattr(route, "methods", None) or [])
    }
    missing = EXPECTED_ROUTES - actual_routes
    assert not missing, f"Declared Vercel entrypoint missing required routes: {sorted(missing)}"
