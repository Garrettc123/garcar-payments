"""
MARS API — Subscription Tier Engine
Garcar Enterprise | garcarenterprise.com

Tiers:
  Starter     $497/mo   — 10K MARS API calls, 1 agent, email support
  Professional $1,497/mo — 100K calls, 5 agents, priority support, Notion sync
  Enterprise  $4,997/mo — Unlimited calls, unlimited agents, dedicated SLA, white-label
  Sovereign   $14,997/mo — Full RHNS stack, custom model fine-tuning, on-call support
"""

import os
import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_REPLACE_ME")

app = FastAPI(title="MARS API — Tier Checkout")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pricing Tiers ──────────────────────────────────────────────────────────────
MARS_TIERS = {
    "starter": {
        "name": "MARS Starter",
        "price_usd": 497,
        "calls": "10,000",
        "agents": 1,
        "support": "Email",
        "features": ["10K MARS API calls/mo", "1 cognitive agent", "Email support", "Notion dashboard"],
        "stripe_price_env": "STRIPE_PRICE_MARS_STARTER",
    },
    "professional": {
        "name": "MARS Professional",
        "price_usd": 1497,
        "calls": "100,000",
        "agents": 5,
        "support": "Priority",
        "features": ["100K MARS API calls/mo", "5 cognitive agents", "Priority support", "Notion + Linear sync", "A/B model testing"],
        "stripe_price_env": "STRIPE_PRICE_MARS_PROFESSIONAL",
    },
    "enterprise": {
        "name": "MARS Enterprise",
        "price_usd": 4997,
        "calls": "Unlimited",
        "agents": -1,
        "support": "Dedicated SLA",
        "features": ["Unlimited MARS API calls", "Unlimited agents", "Dedicated SLA (99.9%)", "White-label rights", "Custom integrations", "Quarterly strategy calls"],
        "stripe_price_env": "STRIPE_PRICE_MARS_ENTERPRISE",
    },
    "sovereign": {
        "name": "MARS Sovereign",
        "price_usd": 14997,
        "calls": "Unlimited + Fine-tune",
        "agents": -1,
        "support": "On-call",
        "features": ["Everything in Enterprise", "Custom model fine-tuning", "RHNS full stack access", "On-call Garrett Carroll", "IP licensing options", "Revenue share structuring"],
        "stripe_price_env": "STRIPE_PRICE_MARS_SOVEREIGN",
    },
}


# ── Landing Page ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def landing_page():
    tier_cards = ""
    for key, tier in MARS_TIERS.items():
        features_html = "".join(f"<li>✅ {f}</li>" for f in tier["features"])
        tier_cards += f"""
        <div class="card">
            <div class="tier-name">{tier['name']}</div>
            <div class="price">${tier['price_usd']:,}<span>/mo</span></div>
            <ul>{features_html}</ul>
            <a href="/checkout/{key}" class="btn">Get Started →</a>
        </div>
        """
    return HTMLResponse(f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MARS API — Garcar Enterprise</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', sans-serif; background: #0a0a0f; color: #e0e0e0; }}
    header {{ background: linear-gradient(135deg, #0d1b2a, #1b2838); padding: 60px 20px; text-align: center; border-bottom: 1px solid #1e3a5f; }}
    header h1 {{ font-size: 3em; color: #00d4ff; letter-spacing: 2px; }}
    header p {{ font-size: 1.2em; color: #aaa; margin-top: 12px; max-width: 600px; margin-left: auto; margin-right: auto; }}
    .badge {{ display: inline-block; background: #00d4ff22; border: 1px solid #00d4ff55; color: #00d4ff; padding: 4px 14px; border-radius: 20px; font-size: 0.85em; margin-top: 16px; }}
    .plans {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 28px; padding: 60px 20px; max-width: 1200px; margin: auto; }}
    .card {{ background: #111827; border: 1px solid #1e3a5f; border-radius: 16px; padding: 36px 28px; width: 260px; transition: transform 0.2s, border-color 0.2s; }}
    .card:hover {{ transform: translateY(-6px); border-color: #00d4ff; }}
    .tier-name {{ font-size: 1.1em; color: #00d4ff; font-weight: 700; letter-spacing: 1px; margin-bottom: 8px; }}
    .price {{ font-size: 2.4em; font-weight: 800; color: #fff; margin-bottom: 20px; }}
    .price span {{ font-size: 0.45em; color: #888; }}
    ul {{ list-style: none; margin-bottom: 28px; }}
    ul li {{ padding: 6px 0; font-size: 0.92em; color: #ccc; border-bottom: 1px solid #1e3a5f22; }}
    .btn {{ display: block; text-align: center; background: linear-gradient(135deg, #00d4ff, #0077ff); color: #000; font-weight: 700; padding: 14px; border-radius: 10px; text-decoration: none; font-size: 1em; transition: opacity 0.2s; }}
    .btn:hover {{ opacity: 0.88; }}
    footer {{ text-align: center; padding: 40px; color: #555; border-top: 1px solid #1e3a5f; margin-top: 40px; }}
  </style>
</head>
<body>
  <header>
    <h1>MARS API</h1>
    <p>Metacognitive AI Runtime System — Production cognitive agents for enterprise automation</p>
    <span class="badge">Powered by Garcar Enterprise · Grandview, TX</span>
  </header>
  <div class="plans">
    {tier_cards}
  </div>
  <footer>
    &copy; 2026 Garcar Enterprise LLC &nbsp;|&nbsp; Grandview, Texas &nbsp;|&nbsp;
    <a href="mailto:hello@garcarenterprise.com" style="color:#00d4ff;">hello@garcarenterprise.com</a>
  </footer>
</body>
</html>
""")


# ── Checkout Session ───────────────────────────────────────────────────────────
@app.get("/checkout/{tier_key}")
def create_checkout(tier_key: str):
    tier = MARS_TIERS.get(tier_key)
    if not tier:
        raise HTTPException(status_code=404, detail=f"Tier '{tier_key}' not found")

    price_id = os.getenv(tier["stripe_price_env"], "")

    if price_id:
        # Use pre-created recurring Stripe Price ID
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url="https://garcarenterprise.com/thank-you?tier=" + tier_key,
            cancel_url="https://garcarenterprise.com/mars",
            metadata={"tier": tier_key, "product": "MARS API"},
        )
    else:
        # Fallback: create price on-the-fly
        price = stripe.Price.create(
            unit_amount=tier["price_usd"] * 100,
            currency="usd",
            recurring={"interval": "month"},
            product_data={"name": tier["name"]},
        )
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price.id, "quantity": 1}],
            success_url="https://garcarenterprise.com/thank-you?tier=" + tier_key,
            cancel_url="https://garcarenterprise.com/mars",
            metadata={"tier": tier_key, "product": "MARS API"},
        )

    return RedirectResponse(session.url, status_code=303)


# ── API Tiers JSON (for frontend integration) ──────────────────────────────────
@app.get("/api/tiers")
def get_tiers():
    return {"tiers": [
        {"key": k, "name": v["name"], "price_usd": v["price_usd"],
         "features": v["features"], "checkout_url": f"/checkout/{k}"}
        for k, v in MARS_TIERS.items()
    ]}


@app.get("/health")
def health():
    return {"status": "live", "service": "mars-api-tiers", "tiers": list(MARS_TIERS.keys())}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)
