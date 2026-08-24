"""
garcar-payments FastAPI application.

Production hardening:
- All secrets loaded via app.settings (pydantic-settings, fail-closed)
- Stripe webhook verifies raw-body HMAC signature (fail-closed when secret set)
- Webhook events recorded idempotently; fulfillment enqueued per-event
- Product allow-list gate on every checkout and fulfillment path
- Signed download endpoint with expiry + entitlement verification
- /livez and /readyz health endpoints
- Structured JSON logging (no secrets in log output)
"""
from __future__ import annotations

import json
import logging
import logging.config
import os
import time
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import stripe
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, BillingEvent, FulfillmentJob, DownloadEntitlement, init_db
from app.settings import get_settings, assert_production_ready
from app.download import verify_download_token

# ── Structured logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
)
logger = logging.getLogger("garcar.payments")

DISPATCH_URL = os.getenv("DISPATCH_URL", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


async def _emit_dispatch(event_type: str, payload: dict) -> None:
    if not DISPATCH_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(
                f"{DISPATCH_URL}/dispatch",
                json={"event_type": event_type, "source_system": "garcar-payments", "payload": payload},
            )
    except Exception:
        pass


# ── Product allow-list ────────────────────────────────────────────────────────
# Only these keys can be sold.  Price IDs are resolved from settings so they
# can be overridden per-environment without editing code.
def _build_offer_catalog() -> dict[str, dict[str, Optional[str]]]:
    s = get_settings()
    return {
        "audit": {
            "name": "Operational Audit",
            "price_id": os.getenv("STRIPE_PRICE_AUDIT") or s.stripe_price_audit or "price_1TGmo7FKGbk21LK5szrPJkRl",
            "mode": "payment",
            "description": "$197 lead-leak / missed-call operational audit",
        },
        "dealdesk": {
            "name": "AI Deal Desk Setup",
            "price_id": os.getenv("STRIPE_PRICE_DEALDESK") or s.stripe_price_dealdesk or "price_1T6lv3FKGbk21LK5J6HCIw2E",
            "mode": "payment",
            "description": "$497 AI call-handling + CRM setup package",
        },
        "starter": {
            "name": "Starter Automation Subscription",
            "price_id": os.getenv("STRIPE_PRICE_STARTER") or s.stripe_price_starter or "price_1TlkwBFKGbk21LK5ZrbIlV6t",
            "mode": "subscription",
            "description": "Starter recurring automation plan",
        },
        "pro": {
            "name": "Pro Automation Subscription",
            "price_id": os.getenv("STRIPE_PRICE_PRO") or s.stripe_price_pro or "price_1TlkwBFKGbk21LK5egwCuCru",
            "mode": "subscription",
            "description": "Professional recurring automation plan",
        },
        "agency": {
            "name": "Agency Automation Subscription",
            "price_id": os.getenv("STRIPE_PRICE_AGENCY") or s.stripe_price_agency or "price_1TIeAJFKGbk21LK5emYRdFRm",
            "mode": "subscription",
            "description": "Agency / managed automation recurring plan",
        },
    }


# Populated at startup
OFFER_CATALOG: dict[str, dict[str, Optional[str]]] = {}
ACTIVE_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {}


class CheckoutRequest(BaseModel):
    plan: str
    email: str
    source: str = "garcar-landing"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail-closed startup validation
    assert_production_ready()

    s = get_settings()
    stripe.api_key = s.stripe_secret_key

    # Populate offer catalog from settings
    OFFER_CATALOG.update(_build_offer_catalog())

    init_db()
    logger.info('"Application started | env=%s"', s.environment)
    yield
    logger.info('"Application shutting down"')


app = FastAPI(title="garcar-payments", lifespan=lifespan)


def _get_cors_origins() -> list[str]:
    return get_settings().cors_allow_origins.split(",")


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _configured_offers() -> list[dict[str, Any]]:
    OFFER_CATALOG.clear()
    OFFER_CATALOG.update(_build_offer_catalog())
    return [
        {
            "key": key,
            "name": offer["name"],
            "price_id": offer.get("price_id"),
            "mode": offer["mode"],
            "description": offer["description"],
            "configured": bool(offer.get("price_id")),
        }
        for key, offer in OFFER_CATALOG.items()
    ]


def _default_url(path: str) -> str:
    base_url = get_settings().app_base_url.rstrip("/")
    return f"{base_url}{path}"


async def notify_slack(message: str) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(SLACK_WEBHOOK_URL, json={"text": message})
    except Exception as exc:
        logger.warning('"notify_slack_failed | reason=%s"', type(exc).__name__)


def _track_subscription_created(obj: dict[str, Any]) -> None:
    sub_id = obj.get("id") or obj.get("subscription")
    if not sub_id:
        return

    plan = (obj.get("metadata") or {}).get("plan", "")
    items = ((obj.get("items") or {}).get("data") or [])
    price = (items[0].get("price") if items else {}) or {}
    unit_amount = price.get("unit_amount") or 0
    mrr = round(float(unit_amount) / 100, 2)

    ACTIVE_SUBSCRIPTIONS[sub_id] = {
        "id": sub_id,
        "customer": obj.get("customer"),
        "plan": plan,
        "mrr": mrr,
        "status": obj.get("status", "active"),
        "current_period_end": obj.get("current_period_end"),
    }


def _track_subscription_deleted(obj: dict[str, Any]) -> Optional[str]:
    sub_id = obj.get("id") or obj.get("subscription")
    if not sub_id:
        return None
    ACTIVE_SUBSCRIPTIONS.pop(sub_id, None)
    return sub_id


def _append_gc_ledger(event: dict, obj: dict) -> None:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
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
            f"{s.supabase_url.rstrip('/')}/rest/v1/gc_ledger",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "apikey": s.supabase_service_key,
                "Authorization": f"******",
                "Prefer": "return=minimal",
            },
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        logger.warning('"gc_ledger write failed: %s"', type(exc).__name__)


# ── Health endpoints ──────────────────────────────────────────────────────────

_start_time = time.time()


@app.get("/livez")
def livez():
    """Kubernetes-style liveness probe — returns 200 if the process is alive."""
    return {"status": "alive", "uptime_s": round(time.time() - _start_time, 1)}


@app.get("/readyz")
def readyz():
    """
    Readiness probe — returns 200 only when the app is configured and ready
    to serve traffic (Stripe key set, DB reachable).
    """
    issues: list[str] = []
    s = get_settings()

    if not s.stripe_secret_key:
        issues.append("STRIPE_SECRET_KEY not set")

    try:
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
    except Exception as exc:
        issues.append(f"DB unreachable: {type(exc).__name__}")

    if issues:
        raise HTTPException(status_code=503, detail={"ready": False, "issues": issues})

    return {"ready": True, "service": "garcar-payments"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "garcar-payments",
        "configured_offers": [offer["key"] for offer in _configured_offers() if offer["configured"]],
    }


# ── Pricing ───────────────────────────────────────────────────────────────────

@app.get("/pricing")
def pricing():
    return {"plans": _configured_offers()}


# ── Checkout ──────────────────────────────────────────────────────────────────

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

    # Product allow-list gate
    offer = OFFER_CATALOG.get(checkout.plan)
    if not offer:
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id = offer.get("price_id")
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Stripe price not configured for plan: {checkout.plan}")

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
        logger.info('"checkout_session_created | plan=%s | mode=%s"', checkout.plan, offer["mode"])
        return {"checkout_url": session.url, "plan": checkout.plan, "mode": offer["mode"]}
    except stripe.StripeError as e:
        logger.error('"stripe_error | type=%s"', type(e).__name__)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception('"checkout_unexpected_error"')
        raise HTTPException(status_code=500, detail=str(e))


# ── Stripe webhook ────────────────────────────────────────────────────────────

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, background: BackgroundTasks):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    # Read the webhook secret fresh each call so test env-var overrides work.
    # The cached settings object is used for all other config.
    import os as _os
    secret = _os.getenv("STRIPE_WEBHOOK_SECRET", "") or get_settings().stripe_webhook_secret

    # Fail-closed: when webhook secret is configured, signature must pass.
    try:
        if secret:
            event = stripe.Webhook.construct_event(payload, sig, secret)
        else:
            event = json.loads(payload.decode("utf-8"))
    except stripe.SignatureVerificationError:
        logger.warning('"webhook_signature_invalid"')
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception:
        logger.warning('"webhook_parse_error"')
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    event_id = event.get("id", "unknown")
    event_type = event.get("type", "unknown")
    obj = event.get("data", {}).get("object", {})

    # Idempotent event recording
    db = SessionLocal()
    try:
        record = BillingEvent(
            event_id=event_id,
            event_type=event_type,
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription"),
            invoice_id=obj.get("invoice") or obj.get("id"),
            payload=payload.decode("utf-8"),
        )
        db.add(record)
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info('"webhook_duplicate | event_id=%s"', event_id)
    finally:
        db.close()

    # Enqueue fulfillment job for paid checkout sessions
    if event_type == "checkout.session.completed":
        _enqueue_fulfillment(event, obj)
    elif event_type == "customer.subscription.created":
        _track_subscription_created(obj)
    elif event_type == "customer.subscription.deleted":
        sub_id = _track_subscription_deleted(obj)
        await notify_slack(f"CHURN: subscription={sub_id or 'unknown'} customer={obj.get('customer', 'unknown')}")
    elif event_type == "invoice.payment_failed":
        amount_due = float(obj.get("amount_due") or 0) / 100
        await notify_slack(
            f"PAYMENT FAILED: invoice={obj.get('id', 'unknown')} customer={obj.get('customer', 'unknown')} "
            f"email={obj.get('customer_email', 'unknown')} amount_usd={amount_due:.2f}"
        )

    _append_gc_ledger(event, obj)

    background.add_task(
        _emit_dispatch,
        f"stripe.{event_type.replace('.', '_')}",
        {
            "event_id": event_id,
            "event_type": event_type,
            "customer_id": obj.get("customer"),
            "subscription_id": obj.get("subscription"),
        },
    )

    logger.info('"webhook_received | event_type=%s | event_id=%s"', event_type, event_id)
    return {"received": True, "event_type": event_type}


def _enqueue_fulfillment(event: dict, obj: dict) -> None:
    """Create a FulfillmentJob row, skipping duplicates (idempotent)."""
    event_id = event.get("id", "unknown")
    # Server-side plan from Stripe metadata — not from untrusted client input
    metadata = obj.get("metadata") or {}
    plan = metadata.get("garcar_plan", "")

    # Product allow-list gate before enqueueing
    if plan and plan not in OFFER_CATALOG:
        logger.warning('"fulfillment_unknown_plan | plan=%s | event_id=%s"', plan, event_id)
        return

    customer_email = (
        (obj.get("customer_details") or {}).get("email")
        or obj.get("customer_email")
        or ""
    )
    checkout_session_id = obj.get("id", "")

    db = SessionLocal()
    try:
        job = FulfillmentJob(
            stripe_event_id=event_id,
            checkout_session_id=checkout_session_id,
            plan=plan,
            customer_email=customer_email,
        )
        db.add(job)
        db.commit()
        logger.info('"fulfillment_job_enqueued | event_id=%s | plan=%s"', event_id, plan)
    except IntegrityError:
        db.rollback()
        logger.info('"fulfillment_job_duplicate | event_id=%s"', event_id)
    finally:
        db.close()


# ── Signed download endpoint ──────────────────────────────────────────────────

@app.get("/download")
def download(
    plan: str = Query(...),
    email: str = Query(...),
    event_id: str = Query(...),
    expires: int = Query(...),
    sig: str = Query(...),
    sv: str = Query(default="v1"),
):
    """
    Issues a short-lived asset delivery response.

    Verifies:
    1. HMAC signature and expiry.
    2. Plan is in the product allow-list.
    3. A DownloadEntitlement exists for this email + event_id.
    """
    if not verify_download_token(plan, email, event_id, expires, sig, sv):
        raise HTTPException(status_code=403, detail="Invalid or expired download link")

    # Product allow-list check
    offer = OFFER_CATALOG.get(plan)
    if not offer:
        raise HTTPException(status_code=404, detail="Product not found")

    # Entitlement check
    db = SessionLocal()
    try:
        entitlement = (
            db.query(DownloadEntitlement)
            .filter_by(customer_email=email, stripe_event_id=event_id, plan=plan)
            .first()
        )
    finally:
        db.close()

    if not entitlement:
        raise HTTPException(status_code=403, detail="No entitlement found for this download")

    logger.info('"download_served | plan=%s | email_hash=%s"', plan, hash(email))
    # In a real deployment, return a RedirectResponse to a pre-signed S3/R2 URL.
    return {
        "ok": True,
        "plan": plan,
        "offer": offer["name"],
        "message": "Entitlement verified. Asset delivery would redirect here in production.",
    }


# ── MRR endpoint ──────────────────────────────────────────────────────────────

@app.get("/mrr")
def mrr():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        subscriptions = list(ACTIVE_SUBSCRIPTIONS.values())
        mrr_total = round(sum(float(sub.get("mrr") or 0.0) for sub in subscriptions), 2)
        return {
            "mrr_usd": mrr_total,
            "active_subscriptions": len(subscriptions),
            "subscriptions": subscriptions,
            "source": "in_memory",
        }

    try:
        req = urllib.request.Request(
            f"{s.supabase_url.rstrip('/')}/rest/v1/gc_ledger?all_ok=eq.true&select=amount_total,currency,customer_email,created_at",
            method="GET",
            headers={
                "apikey": s.supabase_service_key,
                "Authorization": f"******",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            rows = json.loads(resp.read())
    except Exception:
        return {"mrr_usd": 0.0, "active_subscriptions": 0, "subscriptions": [], "source": "fallback_on_error"}

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
        "subscriptions": [],
        "lifetime_revenue_usd": round(lifetime_cents / 100, 2),
        "source": "gc_ledger",
    }


@app.get("/success")
def success(session_id: str = None):
    return {"ok": True, "session_id": session_id, "message": "Payment received. Garcar Enterprise will follow up with onboarding."}
