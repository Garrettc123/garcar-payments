"""Garcar Enterprise payment control plane.

Money-path invariant:
    checkout -> Stripe -> signed webhook -> idempotent DB event -> fulfillment
    -> entitlement/ledger -> downstream dispatch.

Stripe is the payment processor; Garcar's database is the local orchestration
source of truth for event processing and fulfillment state.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import stripe
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import BillingEvent, DownloadEntitlement, FulfillmentJob, SessionLocal, init_db
from app.download import verify_download_token
from app.settings import assert_production_ready, get_settings

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("garcar.payments")
DISPATCH_URL = os.getenv("DISPATCH_URL", "")


def _build_offer_catalog() -> dict[str, dict[str, Optional[str]]]:
    s = get_settings()
    return {
        "audit": {"name": "Operational Audit", "price_id": s.stripe_price_audit or "price_1TGmo7FKGbk21LK5szrPJkRl", "mode": "payment", "description": "$197 operational audit"},
        "dealdesk": {"name": "AI Deal Desk Setup", "price_id": s.stripe_price_dealdesk or "price_1T6lv3FKGbk21LK5J6HCIw2E", "mode": "payment", "description": "$497 AI Deal Desk setup"},
        "starter": {"name": "Starter Automation Subscription", "price_id": s.stripe_price_starter or "price_1TlkwBFKGbk21LK5ZrbIlV6t", "mode": "subscription", "description": "Starter recurring automation"},
        "pro": {"name": "Pro Automation Subscription", "price_id": s.stripe_price_pro or "price_1TlkwBFKGbk21LK5egwCuCru", "mode": "subscription", "description": "Professional recurring automation"},
        "agency": {"name": "Agency Automation Subscription", "price_id": s.stripe_price_agency or "price_1TIeAJFKGbk21LK5emYRdFRm", "mode": "subscription", "description": "Agency managed automation"},
    }

OFFER_CATALOG: dict[str, dict[str, Optional[str]]] = {}


class CheckoutRequest(BaseModel):
    plan: str
    email: str
    source: str = "garcar-landing"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    assert_production_ready()
    s = get_settings()
    stripe.api_key = s.stripe_secret_key
    OFFER_CATALOG.clear()
    OFFER_CATALOG.update(_build_offer_catalog())
    init_db()
    yield


app = FastAPI(title="garcar-payments", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins.split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _offers() -> list[dict[str, Any]]:
    return [{"key": k, "name": v["name"], "mode": v["mode"], "description": v["description"], "configured": bool(v.get("price_id"))} for k, v in OFFER_CATALOG.items()]


def _default_url(path: str) -> str:
    return f"{get_settings().app_base_url.rstrip('/')}{path}"


def _is_paid_checkout(obj: dict) -> bool:
    # Stripe Checkout can report payment_status=paid for completed payments;
    # complete status is accepted as a secondary signal for async methods.
    return obj.get("payment_status") == "paid" or obj.get("status") == "complete"


def _record_event(event: dict, payload: bytes) -> bool:
    obj = event.get("data", {}).get("object", {}) or {}
    db = SessionLocal()
    try:
        db.add(BillingEvent(
            event_id=event["id"], event_type=event["type"], customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"), invoice_id=obj.get("invoice") or obj.get("id"),
            payload=payload.decode("utf-8"),
        ))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
    finally:
        db.close()


def _grant_entitlement(event_id: str, email: str, plan: str) -> None:
    if not email or not plan:
        return
    db = SessionLocal()
    try:
        exists = db.query(DownloadEntitlement).filter_by(stripe_event_id=event_id, customer_email=email.lower(), plan=plan).first()
        if not exists:
            db.add(DownloadEntitlement(stripe_event_id=event_id, customer_email=email.lower(), plan=plan))
            db.commit()
    finally:
        db.close()


def _enqueue_fulfillment(event_id: str, checkout_id: str, plan: str, email: str) -> None:
    db = SessionLocal()
    try:
        if db.query(FulfillmentJob).filter_by(stripe_event_id=event_id).first():
            return
        db.add(FulfillmentJob(stripe_event_id=event_id, checkout_session_id=checkout_id, plan=plan, customer_email=email.lower()))
        db.commit()
    except IntegrityError:
        db.rollback()
    finally:
        db.close()


def _append_gc_ledger(event: dict, obj: dict) -> None:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        return
    event_type = event.get("type", "")
    amount = None
    email = None
    currency = obj.get("currency")
    if event_type == "checkout.session.completed" and _is_paid_checkout(obj):
        amount = obj.get("amount_total")
        email = (obj.get("customer_details") or {}).get("email") or obj.get("customer_email")
    elif event_type == "invoice.paid":
        amount = obj.get("amount_paid") or obj.get("amount_total")
        email = obj.get("customer_email")
    elif event_type == "payment_intent.succeeded":
        amount = obj.get("amount")
        email = obj.get("receipt_email")
    if not amount or not currency or currency.lower() != "usd":
        return
    row = {
        "trace_id": event["id"], "stage": "stripe_event", "stripe_event_id": event["id"],
        "amount_total": int(amount), "currency": currency.lower(), "customer_email": email,
        "outcomes": {"event_type": event_type, "livemode": bool(event.get("livemode")), "settled": True}, "all_ok": True,
    }
    try:
        req = urllib.request.Request(
            f"{s.supabase_url.rstrip('/')}/rest/v1/gc_ledger", data=json.dumps(row).encode(), method="POST",
            headers={"Content-Type": "application/json", "apikey": s.supabase_service_key,
                     "Authorization": f"Bearer {s.supabase_service_key}", "Prefer": "return=minimal"},
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:
        logger.warning("gc_ledger write failed: %s", type(exc).__name__)


async def _emit_dispatch(event_type: str, payload: dict) -> None:
    if not DISPATCH_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(f"{DISPATCH_URL.rstrip('/')}/dispatch", json={"event_type": event_type, "source_system": "garcar-payments", "payload": payload})
            response.raise_for_status()
    except Exception as exc:
        logger.warning("dispatch failed: %s", type(exc).__name__)


@app.get("/livez")
def livez():
    return {"status": "alive", "service": "garcar-payments"}


@app.get("/readyz")
def readyz():
    issues = []
    s = get_settings()
    if not s.stripe_secret_key:
        issues.append("STRIPE_SECRET_KEY not set")
    db = None
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
    except Exception as exc:
        issues.append(f"DB unreachable: {type(exc).__name__}")
    finally:
        if db:
            db.close()
    if issues:
        raise HTTPException(status_code=503, detail={"ready": False, "issues": issues})
    return {"ready": True, "service": "garcar-payments"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "garcar-payments", "configured_offers": [x["key"] for x in _offers() if x["configured"]]}


@app.get("/pricing")
def pricing():
    return {"plans": _offers()}


@app.post("/create-checkout-session")
async def create_checkout_session(request: Request, plan: Optional[str] = Query(None), email: Optional[str] = Query(None)):
    body = {}
    if "application/json" in request.headers.get("content-type", ""):
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(400, "Invalid JSON body") from exc
    checkout = CheckoutRequest(
        plan=(body.get("plan") or plan or "").strip().lower(), email=(body.get("email") or email or "").strip(),
        source=(body.get("source") or "garcar-landing").strip(), success_url=body.get("success_url"), cancel_url=body.get("cancel_url"),
    )
    if "@" not in checkout.email:
        raise HTTPException(400, "A valid email is required")
    offer = OFFER_CATALOG.get(checkout.plan)
    if not offer:
        raise HTTPException(400, "Invalid plan")
    price_id = offer.get("price_id")
    if not price_id:
        raise HTTPException(503, f"Stripe price not configured for plan: {checkout.plan}")
    try:
        session = stripe.checkout.Session.create(
            customer_email=checkout.email, payment_method_types=["card"], line_items=[{"price": price_id, "quantity": 1}],
            mode=offer["mode"], success_url=checkout.success_url or _default_url("/success?session_id={CHECKOUT_SESSION_ID}"),
            cancel_url=checkout.cancel_url or _default_url("/pricing"),
            metadata={"garcar_plan": checkout.plan, "garcar_offer": offer["name"], "source": checkout.source},
        )
        return {"checkout_url": session.url, "plan": checkout.plan, "mode": offer["mode"]}
    except stripe.StripeError as exc:
        logger.error("Stripe checkout error: %s", type(exc).__name__)
        raise HTTPException(502, "Payment processor rejected checkout creation") from exc


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, background: BackgroundTasks):
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    s = get_settings()
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "") or s.stripe_webhook_secret
    try:
        if secret:
            event = stripe.Webhook.construct_event(payload, signature, secret)
        elif s.is_production():
            raise HTTPException(503, "Webhook verification is not configured")
        else:
            event = json.loads(payload.decode("utf-8"))
    except HTTPException:
        raise
    except stripe.SignatureVerificationError as exc:
        raise HTTPException(400, "Invalid webhook signature") from exc
    except Exception as exc:
        raise HTTPException(400, "Invalid webhook payload") from exc

    event_id = event.get("id")
    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {}) or {}
    if not event_id or not event_type:
        raise HTTPException(400, "Stripe event missing id/type")

    # Deduplicate before every external side effect. This is the critical
    # invariant preventing double fulfillment, double ledger entries, and
    # duplicate downstream automation on Stripe retries.
    if not _record_event(event, payload):
        return {"received": True, "duplicate": True, "event_id": event_id}

    if event_type == "checkout.session.completed" and _is_paid_checkout(obj):
        metadata = obj.get("metadata") or {}
        plan = metadata.get("garcar_plan") or ""
        email = ((obj.get("customer_details") or {}).get("email") or obj.get("customer_email") or "").lower().strip()
        if plan in OFFER_CATALOG and email:
            _enqueue_fulfillment(event_id, obj.get("id", ""), plan, email)
            _grant_entitlement(event_id, email, plan)

    _append_gc_ledger(event, obj)
    background.add_task(_emit_dispatch, f"stripe.{event_type.replace('.', '_')}", {"event_id": event_id, "event_type": event_type, "customer_id": obj.get("customer"), "subscription_id": obj.get("subscription")})
    return {"received": True, "event_type": event_type, "event_id": event_id}


@app.get("/download")
def download(plan: str = Query(...), email: str = Query(...), event_id: str = Query(...), expires: int = Query(...), sig: str = Query(...), sv: str = Query("v1")):
    if not verify_download_token(plan, email, event_id, expires, sig, sv):
        raise HTTPException(403, "Invalid or expired download link")
    if plan not in OFFER_CATALOG:
        raise HTTPException(404, "Product not found")
    db = SessionLocal()
    try:
        entitlement = db.query(DownloadEntitlement).filter_by(customer_email=email.lower(), stripe_event_id=event_id, plan=plan).first()
    finally:
        db.close()
    if not entitlement:
        raise HTTPException(403, "No entitlement found for this download")
    return {"ok": True, "plan": plan, "offer": OFFER_CATALOG[plan]["name"]}


@app.get("/orchestration/status")
def orchestration_status():
    db = SessionLocal()
    try:
        return {
            "service": "garcar-payments", "invariants": {
                "webhook_signature_required_in_production": True,
                "event_idempotency": True,
                "paid_checkout_gate": True,
                "fulfillment_idempotency": True,
                "entitlement_idempotency": True,
                "ledger_bearer_auth": True,
            },
            "pending_fulfillment": db.query(FulfillmentJob).filter(FulfillmentJob.status == "pending").count(),
            "processing_fulfillment": db.query(FulfillmentJob).filter(FulfillmentJob.status == "processing").count(),
            "dead_fulfillment": db.query(FulfillmentJob).filter(FulfillmentJob.status == "dead").count(),
            "billing_events": db.query(BillingEvent).count(),
        }
    finally:
        db.close()


@app.get("/mrr")
def mrr():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        return {"mrr_usd": 0.0, "active_subscriptions": 0, "lifetime_revenue_usd": 0.0, "source": "env_fallback"}
    try:
        req = urllib.request.Request(
            f"{s.supabase_url.rstrip('/')}/rest/v1/gc_ledger?all_ok=eq.true&select=amount_total,currency,customer_email,created_at,outcomes",
            headers={"apikey": s.supabase_service_key, "Authorization": f"Bearer {s.supabase_service_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            rows = json.loads(response.read())
    except Exception:
        return {"mrr_usd": 0.0, "active_subscriptions": 0, "lifetime_revenue_usd": 0.0, "source": "fallback_on_error"}
    now = datetime.now(timezone.utc)
    mrr_cents = lifetime_cents = 0
    active_emails: set[str] = set()
    for row in rows:
        if (row.get("currency") or "usd").lower() != "usd":
            continue
        amount = int(row.get("amount_total") or 0)
        lifetime_cents += amount
        try:
            dt = datetime.fromisoformat((row.get("created_at") or "").replace("Z", "+00:00"))
            outcomes = row.get("outcomes") or {}
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            if dt.year == now.year and dt.month == now.month and outcomes.get("event_type") == "invoice.paid":
                mrr_cents += amount
                if row.get("customer_email"):
                    active_emails.add(row["customer_email"])
        except Exception:
            continue
    return {"mrr_usd": round(mrr_cents / 100, 2), "active_subscriptions": len(active_emails), "lifetime_revenue_usd": round(lifetime_cents / 100, 2), "source": "gc_ledger"}


@app.get("/success")
def success(session_id: Optional[str] = None):
    return {"ok": True, "session_id": session_id, "message": "Payment received. Garcar Enterprise will follow up with onboarding."}
