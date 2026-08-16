#!/usr/bin/env python3
"""
Garcar AutoKey — Cloudflare edition (end-to-end)

One run does everything:
  1. Validates required GitHub / env secrets
  2. Creates Stripe products + prices (idempotent)
  3. Registers / rotates Stripe webhook against Workers URL
  4. Pushes every secret into Cloudflare Workers
  5. Optionally creates Queues if missing
"""

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
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_text)
    if check and r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        sys.exit(f"Command failed: {cmd}")
    return r


def stripe(endpoint: str, method: str = "GET", data: dict | None = None) -> dict:
    url = f"https://api.stripe.com/v1/{endpoint}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {os.environ['STRIPE_SECRET_KEY']}")
    if data:
        req.data = urllib.parse.urlencode(data).encode()
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        sys.exit(f"Stripe error on {endpoint}: {body}")


def ensure_product(name: str, amount_cents: int, mode: str) -> str:
    """Return active price ID, creating product+price if needed."""
    q = urllib.parse.quote(f"name:'{name}'")
    res = stripe(f"products/search?query={q}")
    if res.get("data"):
        prod_id = res["data"][0]["id"]
        print(f"[+] Found product '{name}': {prod_id}")
    else:
        print(f"[+] Creating product '{name}'...")
        prod = stripe("products", method="POST", data={"name": name})
        prod_id = prod["id"]

    prices = stripe(f"prices?product={prod_id}&active=true")
    if prices.get("data"):
        return prices["data"][0]["id"]

    price_data = {
        "product": prod_id,
        "currency": "usd",
        "unit_amount": str(amount_cents),
    }
    if mode == "subscription":
        price_data["recurring[interval]"] = "month"
    price = stripe("prices", method="POST", data=price_data)
    print(f"    Created price: {price['id']}")
    return price["id"]


def ensure_queues():
    """Create stripe-events + DLQ if they do not already exist."""
    print("[+] Ensuring Cloudflare Queues exist...")
    r = run(["npx", "wrangler", "queues", "list"], check=False)
    existing = r.stdout or ""
    for q in ("stripe-events", "stripe-events-dlq"):
        if q not in existing:
            print(f"    Creating queue: {q}")
            run(["npx", "wrangler", "queues", "create", q])
        else:
            print(f"    Queue already exists: {q}")


def wrangler_secret(name: str, value: str):
    if not value:
        print(f"  skip {name} (empty)")
        return
    r = run(["npx", "wrangler", "secret", "put", name], check=False, input_text=value)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(f"Failed to put secret {name}")
    print(f"  ✓ {name}")


def main() -> None:
    required = ["STRIPE_SECRET_KEY", "CLOUDFLARE_API_TOKEN"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing required env: {', '.join(missing)}")

    os.environ["CLOUDFLARE_API_TOKEN"] = os.environ["CLOUDFLARE_API_TOKEN"]

    print("=== Garcar AutoKey — Cloudflare End-to-End ===")

    # 0. Queues
    ensure_queues()

    # 1. Stripe catalog
    prices = {
        "STRIPE_PRICE_AUDIT": ensure_product("Operational Audit", 19700, "payment"),
        "STRIPE_PRICE_DEALDESK": ensure_product("AI Deal Desk Setup", 49700, "payment"),
        "STRIPE_PRICE_STARTER": ensure_product("Starter Automation", 99700, "subscription"),
        "STRIPE_PRICE_PRO": ensure_product("Pro Automation", 249700, "subscription"),
        "STRIPE_PRICE_AGENCY": ensure_product("Agency Automation", 499700, "subscription"),
    }

    app_url = (os.environ.get("APP_BASE_URL") or "").rstrip("/")
    if not app_url:
        app_url = os.environ.get(
            "WORKERS_URL",
            "https://garcar-payments.<your-subdomain>.workers.dev",
        )
    webhook_url = f"{app_url}/stripe-webhook"

    # 2. Stripe webhook (rotate if already present)
    print(f"[+] Ensuring webhook → {webhook_url}")
    endpoints = stripe("webhook_endpoints")
    for ep in endpoints.get("data", []):
        if ep["url"] == webhook_url:
            print(f"    Deleting old endpoint {ep['id']} to rotate secret...")
            stripe(f"webhook_endpoints/{ep['id']}", method="DELETE")
            break

    wh = stripe(
        "webhook_endpoints",
        method="POST",
        data={
            "url": webhook_url,
            "enabled_events[0]": "checkout.session.completed",
            "enabled_events[1]": "invoice.paid",
            "enabled_events[2]": "invoice.payment_failed",
            "enabled_events[3]": "customer.subscription.created",
            "enabled_events[4]": "customer.subscription.updated",
            "enabled_events[5]": "customer.subscription.deleted",
            "enabled_events[6]": "payment_intent.succeeded",
            "enabled_events[7]": "payment_intent.payment_failed",
        },
    )
    webhook_secret = wh["secret"]
    print("    New webhook secret obtained")

    download_secret = os.environ.get("DOWNLOAD_SIGNING_SECRET") or secrets.token_hex(32)

    # 3. Push secrets
    print("[+] Pushing secrets into Cloudflare Workers...")
    secrets_map = {
        "STRIPE_SECRET_KEY": os.environ["STRIPE_SECRET_KEY"],
        "STRIPE_WEBHOOK_SECRET": webhook_secret,
        "DOWNLOAD_SIGNING_SECRET": download_secret,
        "APP_BASE_URL": app_url,
        "ENVIRONMENT": os.environ.get("ENVIRONMENT", "production"),
        **prices,
    }

    optional = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "DATABASE_URL",
        "LINEAR_API_KEY",
        "LINEAR_TEAM_ID",
        "NOTION_TOKEN",
        "NOTION_REVENUE_DB_ID",
        "CORS_ALLOW_ORIGINS",
        "HUBSPOT_API_KEY",
        "RESEND_API_KEY",
    ]
    for k in optional:
        if os.environ.get(k):
            secrets_map[k] = os.environ[k]

    for name, value in secrets_map.items():
        wrangler_secret(name, value)

    print("[+] AutoKey complete.")
    print(f"    Service URL : {app_url}")
    print(f"    Webhook URL : {webhook_url}")
    print("    Queues      : stripe-events + stripe-events-dlq")
    print("    Next step   : deploy (already done by the workflow if you used it)")


if __name__ == "__main__":
    main()
