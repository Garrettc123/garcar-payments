#!/usr/bin/env python3
"""Garcar AutoKey — Cloudflare edition."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def run(cmd: list[str], check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
    print(f"> {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, input=input_text)
    if result.stdout:
        print(result.stdout[-2000:])
    if result.stderr:
        print(result.stderr[-2000:], file=sys.stderr)
    if check and result.returncode != 0:
        sys.exit(f"Command failed ({result.returncode}): {cmd}")
    return result


def stripe(endpoint: str, method: str = "GET", data: dict | None = None) -> dict:
    req = urllib.request.Request(f"https://api.stripe.com/v1/{endpoint}", method=method)
    req.add_header("Authorization", f"Bearer {os.environ['STRIPE_SECRET_KEY']}")
    if data:
        req.data = urllib.parse.urlencode(data).encode()
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Stripe error on {endpoint}: {exc.read().decode()}")


def ensure_product(name: str, amount_cents: int, mode: str) -> str:
    q = urllib.parse.quote(f"name:'{name}'")
    products = stripe(f"products/search?query={q}")
    product_id = products["data"][0]["id"] if products.get("data") else stripe("products", method="POST", data={"name": name})["id"]
    prices = stripe(f"prices?product={product_id}&active=true")
    if prices.get("data"):
        return prices["data"][0]["id"]
    data = {"product": product_id, "currency": "usd", "unit_amount": str(amount_cents)}
    if mode == "subscription":
        data["recurring[interval]"] = "month"
    return stripe("prices", method="POST", data=data)["id"]


def ensure_queues() -> None:
    result = run(["npx", "wrangler", "queues", "list"], check=False)
    existing = (result.stdout or "") + (result.stderr or "")
    for queue in ("stripe-events", "stripe-events-dlq"):
        if queue in existing:
            continue
        run(["npx", "wrangler", "queues", "create", queue], check=False)


def wrangler_secret(name: str, value: str) -> None:
    if not value:
        return
    result = run(["npx", "wrangler", "secret", "put", name, "--name", "garcar-payments"], check=False, input_text=value)
    if result.returncode != 0:
        print(f"WARN: could not update Cloudflare secret {name}")


def main() -> None:
    required = ["STRIPE_SECRET_KEY", "CLOUDFLARE_API_TOKEN"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        sys.exit(f"Missing required env: {', '.join(missing)}")

    ensure_queues()
    prices = {
        "STRIPE_PRICE_AUDIT": ensure_product("Operational Audit", 19700, "payment"),
        "STRIPE_PRICE_DEALDESK": ensure_product("AI Deal Desk Setup", 49700, "payment"),
        "STRIPE_PRICE_STARTER": ensure_product("Starter Automation", 99700, "subscription"),
        "STRIPE_PRICE_PRO": ensure_product("Pro Automation", 249700, "subscription"),
        "STRIPE_PRICE_AGENCY": ensure_product("Agency Automation", 499700, "subscription"),
    }

    app_url = (os.environ.get("APP_BASE_URL") or "https://garcar-payments.workers.dev").rstrip("/")
    webhook_url = f"{app_url}/stripe-webhook"
    endpoints = stripe("webhook_endpoints")
    for endpoint in endpoints.get("data", []):
        if endpoint["url"] == webhook_url:
            stripe(f"webhook_endpoints/{endpoint['id']}", method="DELETE")
            break
    webhook = stripe("webhook_endpoints", method="POST", data={
        "url": webhook_url,
        "enabled_events[0]": "checkout.session.completed",
        "enabled_events[1]": "invoice.paid",
        "enabled_events[2]": "invoice.payment_failed",
        "enabled_events[3]": "customer.subscription.created",
        "enabled_events[4]": "customer.subscription.updated",
        "enabled_events[5]": "customer.subscription.deleted",
        "enabled_events[6]": "payment_intent.succeeded",
        "enabled_events[7]": "payment_intent.payment_failed",
    })

    secrets_map = {
        "STRIPE_SECRET_KEY": os.environ["STRIPE_SECRET_KEY"],
        "STRIPE_WEBHOOK_SECRET": webhook["secret"],
        "DOWNLOAD_SIGNING_SECRET": os.environ.get("DOWNLOAD_SIGNING_SECRET") or secrets.token_hex(32),
        "APP_BASE_URL": app_url,
        "ENVIRONMENT": os.environ.get("ENVIRONMENT", "production"),
        **prices,
    }
    for key in [
        "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "DATABASE_URL",
        "LINEAR_API_KEY", "LINEAR_TEAM_ID", "NOTION_TOKEN", "NOTION_REVENUE_DB_ID",
        "CORS_ALLOW_ORIGINS", "HUBSPOT_ACCESS_TOKEN", "ASANA_ACCESS_TOKEN",
        "ASANA_WORKSPACE_GID", "RESEND_API_KEY", "EMAIL_FROM",
    ]:
        if os.environ.get(key):
            secrets_map[key] = os.environ[key]
    for name, value in secrets_map.items():
        wrangler_secret(name, value)

    print(f"AutoKey complete: {app_url} / {webhook_url}")


if __name__ == "__main__":
    main()
