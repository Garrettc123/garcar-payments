import os
from unittest.mock import patch, MagicMock

os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_placeholder")
os.environ.setdefault("STRIPE_PRICE_MARS_STARTER", "price_mars_starter_test")
os.environ.setdefault("STRIPE_PRICE_MARS_PROFESSIONAL", "price_mars_pro_test")

from fastapi.testclient import TestClient
from backend.mars_tiers import app, MARS_TIERS

client = TestClient(app, follow_redirects=False)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "live"
    assert data["service"] == "mars-api-tiers"
    assert set(data["tiers"]) == {"starter", "professional", "enterprise", "sovereign"}


def test_api_tiers_returns_all_four():
    resp = client.get("/api/tiers")
    assert resp.status_code == 200
    tiers = {t["key"]: t for t in resp.json()["tiers"]}
    assert set(tiers.keys()) == {"starter", "professional", "enterprise", "sovereign"}
    assert tiers["starter"]["price_usd"] == 497
    assert tiers["sovereign"]["price_usd"] == 14997


def test_api_tiers_checkout_urls():
    resp = client.get("/api/tiers")
    for tier in resp.json()["tiers"]:
        assert tier["checkout_url"] == f"/checkout/{tier['key']}"


def test_checkout_redirects_with_existing_price_id():
    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_mars_starter"
    with patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create:
        resp = client.get("/checkout/starter")
    assert resp.status_code == 303
    assert resp.headers["location"] == "https://checkout.stripe.com/pay/cs_mars_starter"
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["mode"] == "subscription"
    assert call_kwargs["line_items"][0]["price"] == "price_mars_starter_test"


def test_checkout_fallback_creates_price_on_the_fly():
    mock_price = MagicMock()
    mock_price.id = "price_dynamic_xyz"
    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_mars_enterprise"
    with patch("stripe.Price.create", return_value=mock_price) as mock_pc, \
         patch("stripe.checkout.Session.create", return_value=mock_session) as mock_sc:
        resp = client.get("/checkout/enterprise")
    assert resp.status_code == 303
    mock_pc.assert_called_once()
    call_kwargs = mock_pc.call_args[1]
    assert call_kwargs["unit_amount"] == 4997 * 100
    assert call_kwargs["recurring"]["interval"] == "month"


def test_checkout_invalid_tier():
    resp = client.get("/checkout/nonexistent")
    assert resp.status_code == 404
    assert "nonexistent" in resp.json()["detail"]


def test_landing_page_renders_html():
    full_client = TestClient(app, follow_redirects=True)
    resp = full_client.get("/")
    assert resp.status_code == 200
    assert "MARS API" in resp.text
    assert "Garcar Enterprise" in resp.text
    for key in MARS_TIERS:
        assert f"/checkout/{key}" in resp.text


def test_mars_tiers_prices_are_ascending():
    prices = [MARS_TIERS[k]["price_usd"] for k in ["starter", "professional", "enterprise", "sovereign"]]
    assert prices == sorted(prices)
