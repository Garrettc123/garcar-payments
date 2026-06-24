import os
import json
import httpx
import stripe
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from app.db import SessionLocal, BillingEvent, Subscription, init_db

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PRICE_MAP = {
    "starter": os.getenv("STRIPE_PRICE_STARTER"),
    "pro": os.getenv("STRIPE_PRICE_PRO"),
    "agency": os.getenv("STRIPE_PRICE_AGENCY"),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="garcar-payments", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def notify_slack(msg: str) -> None:
    url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not url:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"text": msg}, timeout=5)
    except Exception:
        pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "garcar-payments"}


@app.get("/pricing")
def pricing():
    return {"plans": [
        {"key": k, "price_id": v} for k, v in PRICE_MAP.items() if v
    ]}


@app.get("/mrr")
def mrr_summary():
    db = SessionLocal()
    try:
        active = db.query(Subscription).filter(Subscription.status == "active").all()
        total_mrr = sum(s.mrr for s in active)
        return {
            "active_subscriptions": len(active),
            "mrr_usd": round(total_mrr, 2),
            "subscriptions": [
                {"id": s.stripe_subscription_id, "plan": s.plan, "mrr": s.mrr, "status": s.status}
                for s in active
            ],
        }
    finally:
        db.close()


@app.post("/create-checkout-session")
def create_checkout_session(plan: str, email: str):
    price_id = PRICE_MAP.get(plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan")

    base_url = os.getenv("APP_BASE_URL", "http://localhost:8000")
    try:
        session = stripe.checkout.Session.create(
            customer_email=email,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=f"{base_url}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/pricing",
        )
        return {"checkout_url": session.url}
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
    event_type = event.get("type", "unknown")
    sub_id = obj.get("id", "")

    db = SessionLocal()
    try:
        record = BillingEvent(
            event_id=event.get("id", "unknown"),
            event_type=event_type,
            customer_id=obj.get("customer"),
            subscription_id=obj.get("subscription") or sub_id,
            invoice_id=obj.get("invoice") or sub_id,
            payload=payload.decode("utf-8"),
        )
        db.add(record)
        db.commit()
    except IntegrityError:
        db.rollback()
    finally:
        db.close()

    if event_type == "customer.subscription.created":
        items = obj.get("items", {}).get("data", [])
        unit_amount = items[0].get("price", {}).get("unit_amount", 0) if items else 0
        plan = obj.get("metadata", {}).get("plan") or (items[0].get("price", {}).get("id") if items else None)
        period_end = obj.get("current_period_end")
        if sub_id:
            db2 = SessionLocal()
            try:
                existing = db2.query(Subscription).filter(
                    Subscription.stripe_subscription_id == sub_id
                ).first()
                if existing:
                    existing.status = obj.get("status", "active")
                    existing.mrr = unit_amount / 100
                    existing.plan = plan
                else:
                    db2.add(Subscription(
                        stripe_subscription_id=sub_id,
                        stripe_customer_id=str(obj.get("customer", "")),
                        status=obj.get("status", "active"),
                        plan=plan,
                        mrr=unit_amount / 100,
                        current_period_end=datetime.utcfromtimestamp(period_end) if period_end else None,
                    ))
                db2.commit()
            except Exception:
                db2.rollback()
            finally:
                db2.close()

    elif event_type == "customer.subscription.updated":
        items = obj.get("items", {}).get("data", [])
        unit_amount = items[0].get("price", {}).get("unit_amount", 0) if items else 0
        period_end = obj.get("current_period_end")
        if sub_id:
            db2 = SessionLocal()
            try:
                row = db2.query(Subscription).filter(
                    Subscription.stripe_subscription_id == sub_id
                ).first()
                if row:
                    row.status = obj.get("status", row.status)
                    row.mrr = unit_amount / 100
                    if period_end:
                        row.current_period_end = datetime.utcfromtimestamp(period_end)
                    db2.commit()
            except Exception:
                db2.rollback()
            finally:
                db2.close()

    elif event_type == "customer.subscription.deleted":
        if sub_id:
            db2 = SessionLocal()
            try:
                row = db2.query(Subscription).filter(
                    Subscription.stripe_subscription_id == sub_id
                ).first()
                if row:
                    row.status = "cancelled"
                    row.cancelled_at = datetime.utcnow()
                    row.mrr = 0
                    db2.commit()
            except Exception:
                db2.rollback()
            finally:
                db2.close()
        plan = obj.get("metadata", {}).get("plan", "unknown")
        await notify_slack(
            f"\U0001f6a8 CHURN: Subscription `{sub_id}` cancelled. "
            f"Plan: {plan} | Customer: {obj.get('customer', 'unknown')}"
        )

    elif event_type == "invoice.payment_failed":
        amount = (obj.get("amount_due") or 0) / 100
        await notify_slack(
            f"⚠️ PAYMENT FAILED: Customer `{obj.get('customer_email', 'unknown')}` "
            f"| Amount: ${amount:.2f} | Invoice: {obj.get('id', 'unknown')}"
        )

    return {"received": True, "event_type": event_type}


@app.get("/success")
def success(session_id: str = None):
    return {"ok": True, "session_id": session_id}
