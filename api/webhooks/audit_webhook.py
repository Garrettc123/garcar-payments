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
AUDIT_PRICE_ID = "price_1U3I2kFKGbk21LK5CQ4nXqcx"

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

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        # Check if this is the Automation Audit product
        # In a real scenario, you might expand line_items or check metadata
        if session.get("metadata", {}).get("source") == "Garcar Unified Command Center":
            # 1. Insert into Supabase
            data, count = supabase.table("audit_orders").insert({
                "checkout_session_id": session["id"],
                "customer_email": session.get("customer_details", {}).get("email"),
                "status": "paid",
                "stripe_product_id": AUDIT_PRODUCT_ID
            }).execute()

            # 2. Linear issue creation logic would go here
            # (Note: Linear workspace hit free limit, manual tracking recommended for now)

    return {"status": "success"}