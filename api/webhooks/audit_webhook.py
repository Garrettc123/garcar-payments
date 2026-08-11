import os
import stripe
from fastapi import APIRouter, Request, HTTPException
from supabase import create_client, Client

router = APIRouter()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

AUDIT_PRODUCT_ID = "prod_V3OplsZcTcvRg9"
RETAINER_PRODUCT_ID = "prod_V3R8CoOuRdsHTP"

@router.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle Checkout Sessions
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        # 1. Insert into Supabase
        data, count = supabase.table("audit_orders").insert({
            "checkout_session_id": session["id"],
            "customer_email": session.get("customer_details", {}).get("email"),
            "status": "paid",
            "stripe_product_id": session.get("metadata", {}).get("product_id", "unknown")
        }).execute()

    return {"status": "success"}