import os
import json
import stripe
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from app.db import SessionLocal, BillingEvent, init_db

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


@app.get("/health")
def health():
    return {"status": "ok", "service": "garcar-payments"}


@app.get("/pricing")
def pricing():
    return {"plans": [
        {"key": k, "price_id": v} for k, v in PRICE_MAP.items() if v
    ]}


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

    return {"received": True, "event_type": event.get("type")}


@app.get("/success")
def success(session_id: str = None):
    return {"ok": True, "session_id": session_id}
