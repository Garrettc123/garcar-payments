"""Bootstrap safety checks; all provider calls are stubbed, never live."""
import pytest
from scripts import autokey_bootstrap_cf as bootstrap


def test_autokey_rejects_legacy_stripe_account(monkeypatch):
    monkeypatch.setattr(bootstrap, "stripe", lambda endpoint, **kw: {"id": "acct_legacy"})
    with pytest.raises(SystemExit, match="designated active Garcar"):
        bootstrap.assert_active_account()


def test_autokey_accepts_exact_designated_account(monkeypatch):
    monkeypatch.setattr(bootstrap, "stripe", lambda endpoint, **kw: {
        "id": bootstrap.EXPECTED_STRIPE_ACCOUNT_ID
    })
    bootstrap.assert_active_account()


def test_autokey_reuses_only_matching_price(monkeypatch):
    calls = []

    def stub(endpoint, method="GET", data=None):
        calls.append((endpoint, method))
        if endpoint.startswith("products/search"):
            return {"data": [{"id": "prod_fake"}]}
        if endpoint.startswith("prices?"):
            return {"data": [
                {"id": "price_old", "active": True, "currency": "usd",
                 "unit_amount": 19700, "recurring": None},
                {"id": "price_47", "active": True, "currency": "usd",
                 "unit_amount": 4700, "recurring": None},
            ]}
        raise AssertionError("unexpected Stripe API write")

    monkeypatch.setattr(bootstrap, "stripe", stub)
    assert bootstrap.ensure_product("Lead Leak Audit", 4700, "payment") == "price_47"
    assert all(method == "GET" for _, method in calls)


def test_autokey_does_not_reuse_wrong_amount(monkeypatch):
    writes = []

    def stub(endpoint, method="GET", data=None):
        if endpoint.startswith("products/search"):
            return {"data": [{"id": "prod_fake"}]}
        if endpoint.startswith("prices?"):
            return {"data": [{"id": "price_old", "active": True, "currency": "usd",
                              "unit_amount": 19700, "recurring": None}]}
        if endpoint == "prices" and method == "POST":
            writes.append(data)
            return {"id": "price_correct"}
        raise AssertionError("unrecognized request")

    monkeypatch.setattr(bootstrap, "stripe", stub)
    assert bootstrap.ensure_product("Lead Leak Audit", 4700, "payment") == "price_correct"
    assert writes == [{"product": "prod_fake", "currency": "usd", "unit_amount": "4700"}]


def test_autokey_existing_webhook_never_deleted(monkeypatch):
    required = [
        "STRIPE_SECRET_KEY", "CLOUDFLARE_API_TOKEN", "APP_BASE_URL", "DATABASE_URL",
        "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "HUBSPOT_ACCESS_TOKEN",
        "ASANA_ACCESS_TOKEN", "ASANA_WORKSPACE_GID", "NOTION_TOKEN",
        "NOTION_REVENUE_DB_ID", "LINEAR_API_KEY", "LINEAR_TEAM_ID",
        "RESEND_API_KEY", "EMAIL_FROM", "DOWNLOAD_SIGNING_SECRET",
    ]
    for key in required:
        monkeypatch.setenv(key, "regression-only")
    monkeypatch.setenv("APP_BASE_URL", "https://garcar-payments.garrettc123.workers.dev")
    calls = []

    def stub(endpoint, method="GET", data=None):
        calls.append((endpoint, method))
        if endpoint == "account":
            return {"id": bootstrap.EXPECTED_STRIPE_ACCOUNT_ID}
        if endpoint.startswith("webhook_endpoints?"):
            return {"data": [
                {"id": "we_existing", "url": "https://garcar-payments.garrettc123.workers.dev/stripe-webhook"}
            ], "has_more": False}
        raise AssertionError("unsafe Stripe call")

    monkeypatch.setattr(bootstrap, "stripe", stub)
    monkeypatch.setattr(bootstrap, "ensure_queues",
                        lambda: (_ for _ in ()).throw(AssertionError("mutation must not happen")))
    with pytest.raises(SystemExit, match="already registered"):
        bootstrap.main()
    assert calls == [("account", "GET"), ("webhook_endpoints?limit=100", "GET")]
