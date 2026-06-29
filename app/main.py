import os
import json
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import stripe
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, BillingEvent, init_db

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Canonical sellable Garcar Enterprise offers.
# One-time offers power the public roofing/home-services landing page.
# Subscription offers support the recurring SaaS / managed-automation ladder.
# Each price_id defaults to the matching live price already present in the
# Garcar Stripe account; set STRIPE_PRICE_* env vars to override.
OFFER_CATALOG: dict[str, dict[str, Optional[str]]] = {
    "audit": {
        "name": "Operational Audit",
        "price_id": os.getenv("STRIPE_PRICE_AUDIT", "price_1TGmo7FKGbk21LK5szrPJkRl"),
        "mode": "payment",
        "description": "$197 lead-leak / missed-call operational audit",
    },
    "dealdesk": {
        "name": "AI Deal Desk Setup",
        "price_id": os.getenv("STRIPE_PRICE_DEALDESK", "price_1T6lv3FKGbk21LK5J6HCIw2E"),
        "mode": "payment",
        "description": "$497 AI call-handling + CRM setup package",
    },
    "starter": {
        "name": "Starter Automation Subscription",
        "price_id": os.getenv("STRIPE_PRICE_STARTER", "price_1TlkwBFKGbk21LK5ZrbIlV6t"),
        "mode": "subscription",
        "description": "Starter recurring automation plan",
    },
    "pro": {
        "name": "Pro Automation Subscription",
        "price_id": os.getenv("STRIPE_PRICE_PRO", "price_1TlkwBFKGbk21LK5egwCuCru"),
        "mode": "subscription",
        "description": "Professional recurring automation plan",
    },
    "agency": {
        "name": "Agency Automation Subscription",
        "price_id": os.getenv("STRIPE_PRICE_AGENCY", "price_1TIeAJFKGbk21LK5emYRdFRm"),
        "mode": "subscription",
        "description": "Agency / managed automation recurring plan",
    },
}


class CheckoutRequest(BaseModel):
    plan: str
    email: str
    source: str = "garcar-landing"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="garcar-payments", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _configured_offers() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "name": offer["name"],
            "mode": offer["mode"],
            "description": offer["description"],
            "configured": bool(offer.get("price_id")),
        }
        for key, offer in OFFER_CATALOG.items()
    ]


def _default_url(path: str) -> str:
    base_url = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base_url}{path}"


def _append_gc_ledger(event: dict, obj: dict) -> None:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        return

    event_type = event.get("type", "unknown")
    amount_total: Optional[int] = None
    currency: Optional[str] = None
    customer_email: Optional[str] = None

    if event_type == "checkout.session.completed":
        amount_total = obj.get("amount_total")
        currency = obj.get("currency")
        customer_email = (obj.get("customer_details") or {}).get("email") or obj.get("customer_email")
    elif event_type in ("invoice.paid", "invoice.payment_succeeded"):
        amount_total = obj.get("amount_paid") or obj.get("amount_total")
        currency = obj.get("currency")
        customer_email = obj.get("customer_email")
    elif event_type == "payment_intent.succeeded":
        amount_total = obj.get("amount")
        currency = obj.get("currency")
        customer_email = obj.get("receipt_email")

    row = {
        "trace_id": event.get("id", "unknown"),
        "stage": "stripe_event",
        "stripe_event_id": event.get("id"),
        "amount_total": amount_total,
        "currency": currency,
        "customer_email": customer_email,
        "outcomes": {"event_type": event_type, "livemode": event.get("livemode", False)},
        "all_ok": True,
    }

    try:
        data = json.dumps(row).encode("utf-8")
        req = urllib.request.Request(
            f"{supabase_url.rstrip('/')}/rest/v1/gc_ledger",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Prefer": "return=minimal",
            },
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "garcar-payments",
        "configured_offers": [offer["key"] for offer in _configured_offers() if offer["configured"]],
    }


@app.get("/pricing")
def pricing():
    return {"plans": _configured_offers()}


@app.post("/create-checkout-session")
async def create_checkout_session(
    request: Request,
    plan: Optional[str] = Query(default=None),
    email: Optional[str] = Query(default=None),
):
    body: dict[str, Any] = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

    checkout = CheckoutRequest(
        plan=(body.get("plan") or plan or "").strip().lower(),
        email=(body.get("email") or email or "").strip(),
        source=(body.get("source") or "garcar-landing").strip(),
        success_url=body.get("success_url"),
        cancel_url=body.get("cancel_url"),
    )

    if not checkout.email or "@" not in checkout.email:
        raise HTTPException(status_code=400, detail="A valid email is required")

    offer = OFFER_CATALOG.get(checkout.plan)
    if not offer:
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id = offer.get("price_id")
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Stripe price is not configured for plan: {checkout.plan}")

    try:
        session = stripe.checkout.Session.create(
            customer_email=checkout.email,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode=offer["mode"],
            success_url=checkout.success_url or _default_url("/success?session_id={CHECKOUT_SESSION_ID}"),
            cancel_url=checkout.cancel_url or _default_url("/pricing"),
            metadata={
                "garcar_plan": checkout.plan,
                "garcar_offer": offer["name"] or checkout.plan,
                "source": checkout.source,
            },
        )
        return {"checkout_url": session.url, "plan": checkout.plan, "mode": offer["mode"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        if secret:
            event = stripe.Webhook.construct_event(payload, sig, secret)
        else:
            event = json.loads(payload.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook")

    obj = event.get("data", {}).get("object", {})
    db = SessionLocal()
    try:
        record = BillingEvent(
            event_id=event.get("id", "unknown"),
            event_type=event.get("type", "unknown"),
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            invoice_id=obj.get("invoice") or obj.get("id"),
            payload=payload.decode("utf-8"),
        )
        db.add(record)
        db.commit()
    except IntegrityError:
        db.rollback()
    finally:
        db.close()

    _append_gc_ledger(event, obj)

    return {"received": True, "event_type": event.get("type")}


@app.get("/mrr")
def mrr():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        fallback = float(os.getenv("CURRENT_MRR", "0"))
        return {"mrr_usd": fallback, "active_subscriptions": 0, "source": "env_fallback"}

    try:
        req = urllib.request.Request(
            f"{supabase_url.rstrip('/')}/rest/v1/gc_ledger?all_ok=eq.true&select=amount_total,currency,customer_email,created_at",
            method="GET",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            rows = json.loads(resp.read())
    except Exception:
        fallback = float(os.getenv("CURRENT_MRR", "0"))
        return {"mrr_usd": fallback, "active_subscriptions": 0, "source": "fallback_on_error"}

    now = datetime.now(timezone.utc)
    mrr_cents = 0
    lifetime_cents = 0
    active_emails: set[str] = set()

    for row in rows:
        amount = row.get("amount_total") or 0
        if (row.get("currency") or "usd").lower() != "usd":
            continue
        lifetime_cents += amount
        try:
            dt = datetime.fromisoformat((row.get("created_at") or "").replace("Z", "+00:00"))
            if dt.year == now.year and dt.month == now.month:
                mrr_cents += amount
                if row.get("customer_email"):
                    active_emails.add(row["customer_email"])
        except Exception:
            pass

    return {
        "mrr_usd": round(mrr_cents / 100, 2),
        "active_subscriptions": len(active_emails),
        "lifetime_revenue_usd": round(lifetime_cents / 100, 2),
        "source": "gc_ledger",
    }


@app.get("/success")
def success(session_id: str = None):
    return {"ok": True, "session_id": session_id, "message": "Payment received. Garcar Enterprise will follow up with onboarding."}
