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

import asyncio

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
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, BillingEvent, FulfillmentJob, DownloadEntitlement, Subscription, init_db
from app.settings import get_settings, assert_production_ready
from app.download import verify_download_token
from app.api_key_auth import require_admin_key
from app.stripe_sig import SignatureError, parse_verified_event

# ── Structured logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
)
logger = logging.getLogger("garcar.payments")

DISPATCH_URL = os.getenv("DISPATCH_URL", "")


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


async def notify_slack(message: str) -> None:
    """Send an alert to Slack via incoming webhook. No-ops when SLACK_WEBHOOK_URL is not set."""
    slack_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not slack_url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(slack_url, json={"text": message})
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
            "price_id": s.stripe_price_audit or "price_1TGmo7FKGbk21LK5szrPJkRl",
            "mode": "payment",
            "description": "$197 lead-leak / missed-call operational audit",
        },
        "dealdesk": {
            "name": "AI Deal Desk Setup",
            "price_id": s.stripe_price_dealdesk or "price_1T6lv3FKGbk21LK5J6HCIw2E",
            "mode": "payment",
            "description": "$497 AI call-handling + CRM setup package",
        },
        "starter": {
            "name": "Starter Automation Subscription",
            "price_id": s.stripe_price_starter or "price_1TlkwBFKGbk21LK5ZrbIlV6t",
            "mode": "subscription",
            "description": "Starter recurring automation plan",
        },
        "pro": {
            "name": "Pro Automation Subscription",
            "price_id": s.stripe_price_pro or "price_1TlkwBFKGbk21LK5egwCuCru",
            "mode": "subscription",
            "description": "Professional recurring automation plan",
        },
        "agency": {
            "name": "Agency Automation Subscription",
            "price_id": s.stripe_price_agency or "price_1TIeAJFKGbk21LK5emYRdFRm",
            "mode": "subscription",
            "description": "Agency / managed automation recurring plan",
        },
    }


# Populated at startup
OFFER_CATALOG: dict[str, dict[str, Optional[str]]] = {}


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
    mesh_task = None
    if os.getenv("GARCAR_MESH_PUBLISH_ENABLED", "").lower() == "true":
        async def run_mesh_reporting():
            from mesh_heartbeat import send_heartbeat
            while True:
                try:
                    await asyncio.to_thread(send_heartbeat, "degraded")
                except Exception:
                    logger.warning("Signed mesh heartbeat unverified")
                await asyncio.sleep(300)
        mesh_task = asyncio.create_task(run_mesh_reporting())
    try:
        yield
    finally:
        if mesh_task is not None:
            mesh_task.cancel()
            try:
                await mesh_task
            except asyncio.CancelledError:
                pass
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
    return [
        {
            "key": key,
            "name": offer["name"],
            "mode": offer["mode"],
            "description": offer["description"],
            "price_id": offer.get("price_id") or "",
            "configured": bool(offer.get("price_id")),
        }
        for key, offer in OFFER_CATALOG.items()
        if offer.get("price_id")
    ]


def _default_url(path: str) -> str:
    base_url = get_settings().app_base_url.rstrip("/")
    return f"{base_url}{path}"


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
                "Authorization": f"Bearer {s.supabase_service_key}",
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
    secret = (_os.getenv("STRIPE_WEBHOOK_SECRET", "") or get_settings().stripe_webhook_secret or "").strip()

    # Hardening audit Oct 2026: fail closed. Without a signing secret we cannot tell a real
    # Stripe event from a forged one, so refuse everything (503) instead of trusting the body.
    if not secret:
        logger.error('"webhook_not_configured | STRIPE_WEBHOOK_SECRET is not set"')
        raise HTTPException(status_code=503, detail="Webhook not configured")
    if not sig:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    # Verify with the repo's stdlib verifier (same Stripe v1 scheme as the edge worker).
    # It returns a plain dict, so the .get() calls below work on every stripe SDK version
    # (newer SDKs return an Event object that no longer supports .get()).
    try:
        event = parse_verified_event(payload.decode("utf-8"), sig, secret)
    except SignatureError:
        logger.warning('"webhook_signature_invalid"')
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception:
        logger.warning('"webhook_parse_error"')
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    event_id = event.get("id", "unknown")
    event_type = event.get("type", "unknown")
    obj = event.get("data", {}).get("object", {})

    # Idempotent event recording
    is_new_event = True
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
        is_new_event = False
        logger.info('"webhook_duplicate | event_id=%s"', event_id)
    finally:
        db.close()

    # Subscription state + Slack alerts. Skipped for duplicate deliveries so a Stripe
    # retry cannot re-send a churn / payment-failed alert.
    if is_new_event:
        await _handle_subscription_event(event_type, obj)

    # Enqueue fulfillment job for paid checkout sessions
    if event_type == "checkout.session.completed":
        _enqueue_fulfillment(event, obj)

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


def _subscription_unit_amount_and_plan(obj: dict) -> tuple[int, Optional[str], str]:
    """Return (monthly-normalized amount in cents, plan, currency) from a Stripe subscription object."""
    items = (obj.get("items") or {}).get("data") or []
    price = (items[0].get("price") or {}) if items else {}
    amount = int(price.get("unit_amount") or 0)
    interval = (price.get("recurring") or {}).get("interval", "month")
    interval_count = int((price.get("recurring") or {}).get("interval_count") or 1)
    # Normalize to monthly so annual plans are not counted at 12x in MRR.
    if interval == "year":
        amount = round(amount / (12 * interval_count))
    elif interval == "week":
        amount = round(amount * 52 / 12 / interval_count)
    elif interval == "day":
        amount = round(amount * 365 / 12 / interval_count)
    elif interval == "month" and interval_count > 1:
        amount = round(amount / interval_count)
    plan = (obj.get("metadata") or {}).get("plan") or price.get("id")
    currency = (price.get("currency") or obj.get("currency") or "usd").lower()
    return amount, plan, currency


async def _handle_subscription_event(event_type: str, obj: dict) -> None:
    """Track subscription lifecycle for MRR and send churn / payment-failure alerts.

    Regression fix: commit f2e844f (garcar-dispatch emit) overwrote this logic with a stale
    copy of the file, silently disabling it. Restored from 531fa9f (GAR-494).
    """
    sub_id = obj.get("id", "")

    if event_type in ("customer.subscription.created", "customer.subscription.updated") and sub_id:
        amount, plan, currency = _subscription_unit_amount_and_plan(obj)
        status = obj.get("status", "active")
        period_end = obj.get("current_period_end")
        db = SessionLocal()
        try:
            row = db.query(Subscription).filter(Subscription.subscription_id == sub_id).first()
            if row:
                row.status = status
                row.unit_amount = amount
                row.currency = currency
                if plan:
                    row.plan = plan
                if period_end:
                    row.current_period_end = int(period_end)
            else:
                db.add(Subscription(
                    subscription_id=sub_id,
                    customer_id=str(obj.get("customer") or ""),
                    plan=plan,
                    unit_amount=amount,
                    currency=currency,
                    status=status,
                    current_period_end=int(period_end) if period_end else None,
                ))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception('"subscription_upsert_failed | subscription_id=%s"', sub_id)
        finally:
            db.close()

    elif event_type == "customer.subscription.deleted":
        if sub_id:
            db = SessionLocal()
            try:
                row = db.query(Subscription).filter(Subscription.subscription_id == sub_id).first()
                if row:
                    row.status = "cancelled"
                    row.unit_amount = 0
                    db.commit()
            except Exception:
                db.rollback()
                logger.exception('"subscription_cancel_failed | subscription_id=%s"', sub_id)
            finally:
                db.close()
        plan = (obj.get("metadata") or {}).get("plan", "unknown")
        await notify_slack(
            f"\U0001f6a8 CHURN: Subscription `{sub_id}` cancelled. "
            f"Plan: {plan} | Customer: {obj.get('customer', 'unknown')}"
        )

    elif event_type == "invoice.payment_failed":
        amount_due = (obj.get("amount_due") or 0) / 100
        await notify_slack(
            f"\u26a0\ufe0f PAYMENT FAILED: Customer `{obj.get('customer_email', 'unknown')}` "
            f"| Amount: ${amount_due:.2f} | Invoice: {obj.get('id', 'unknown')}"
        )


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

# Hardening audit Oct 2026: revenue figures need PAYMENTS_ADMIN_API_KEY (503 if unset).
@app.get("/mrr", dependencies=[Depends(require_admin_key)])
def mrr():
    """MRR from tracked subscriptions (source of truth). If Supabase is configured, the
    gc_ledger cash figures are added under `ledger` for reconciliation."""
    db = SessionLocal()
    try:
        active = db.query(Subscription).filter(Subscription.status == "active").all()
        subs = [
            {
                "id": r.subscription_id,
                "plan": r.plan,
                "mrr": (r.unit_amount or 0) / 100,
                "status": r.status,
            }
            for r in active
            if (r.currency or "usd").lower() == "usd"
        ]
    finally:
        db.close()

    result: dict[str, Any] = {
        "mrr_usd": round(sum(x["mrr"] for x in subs), 2),
        "active_subscriptions": len(subs),
        "subscriptions": subs,
        "source": "subscriptions",
    }
    ledger = _gc_ledger_summary()
    if ledger is not None:
        result["ledger"] = ledger
    return result


def _gc_ledger_summary() -> Optional[dict[str, Any]]:
    """Cash-basis figures from the Supabase gc_ledger table; None when unconfigured or unreachable."""
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        return None
    try:
        req = urllib.request.Request(
            f"{s.supabase_url.rstrip('/')}/rest/v1/gc_ledger?all_ok=eq.true&select=amount_total,currency,customer_email,created_at",
            method="GET",
            headers={
                "apikey": s.supabase_service_key,
                "Authorization": f"Bearer {s.supabase_service_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            rows = json.loads(resp.read())
    except Exception:
        logger.warning('"gc_ledger_unreachable"')
        return None

    now = datetime.now(timezone.utc)
    month_cents = 0
    lifetime_cents = 0
    emails: set[str] = set()
    for row in rows:
        amount = row.get("amount_total") or 0
        if (row.get("currency") or "usd").lower() != "usd":
            continue
        lifetime_cents += amount
        try:
            dt = datetime.fromisoformat((row.get("created_at") or "").replace("Z", "+00:00"))
            if dt.year == now.year and dt.month == now.month:
                month_cents += amount
                if row.get("customer_email"):
                    emails.add(row["customer_email"])
        except Exception:
            pass
    return {
        "this_month_usd": round(month_cents / 100, 2),
        "paying_customers_this_month": len(emails),
        "lifetime_revenue_usd": round(lifetime_cents / 100, 2),
    }


@app.get("/success")
def success(session_id: str = None):
    return {"ok": True, "session_id": session_id, "message": "Payment received. Garcar Enterprise will follow up with onboarding."}
