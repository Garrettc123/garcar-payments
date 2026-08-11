import os
import stripe
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from supabase import create_client, Client
import httpx  # For calling external MARS/Resend/CRM APIs

router = APIRouter()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

AUDIT_PRODUCT_ID = "prod_V3OplsZcTcvRg9"
RETAINER_PRODUCT_ID = "prod_V3R8CoOuRdsHTP"

async def trigger_mars_intake(email: str, session_id: str):
    """
    Phase A: MARS Triage Agent Trigger
    Called in the background after successful payment for the $299 Audit.
    Fires a webhook/API call to your MARS orchestration layer to send the intake form
    via Resend and begin the Zero-Human diagnostic sequence.
    """
    mars_endpoint = os.getenv("MARS_ORCHESTRATOR_URL")
    if not mars_endpoint:
        return
    
    payload = {
        "event": "audit_purchased",
        "customer_email": email,
        "stripe_session_id": session_id,
        "instructions": "Execute Phase A: Send technical diagnostic intake via Resend. Await response, process via RHNS, and map failing workflows."
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"{mars_endpoint}/trigger", json=payload)
        except Exception as e:
            print(f"Failed to trigger MARS agent: {e}")

@router.post("/stripe-webhook")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
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
        customer_email = session.get("customer_details", {}).get("email")
        product_id = session.get("metadata", {}).get("product_id", "unknown")
        
        # 1. Insert into Supabase
        data, count = supabase.table("audit_orders").insert({
            "checkout_session_id": session["id"],
            "customer_email": customer_email,
            "status": "paid",
            "stripe_product_id": product_id
        }).execute()

        # 2. Trigger MARS Autonomous Intake if this is the $299 Audit
        if product_id == AUDIT_PRODUCT_ID and customer_email:
            background_tasks.add_task(trigger_mars_intake, customer_email, session["id"])

    return {"status": "success"}