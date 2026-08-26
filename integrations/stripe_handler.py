"""Stripe webhook handler — routes payment events to downstream systems."""
import stripe
import logging
from integrations.config import Config
from integrations.hubspot_handler import create_deal, close_deal
from integrations.supabase_handler import provision_tenant
from integrations.linear_handler import create_onboarding_project
from integrations.notion_handler import create_client_workspace
from integrations.docusign_handler import send_contract
from integrations.shopify_handler import fulfill_order

logger = logging.getLogger(__name__)
stripe.api_key = Config.STRIPE_SECRET_KEY


def handle_stripe_webhook(payload: bytes, sig_header: str) -> dict:
    """Verify and dispatch Stripe webhook events."""
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, Config.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Stripe signature verification failed: {e}")
        raise ValueError("Invalid Stripe signature")

    event_type = event["type"]
    data = event["data"]["object"]
    logger.info(f"Stripe event received: {event_type} | id={data.get('id')}")

    if event_type == "checkout.session.completed":
        _on_checkout_complete(data)
    elif event_type == "invoice.payment_succeeded":
        _on_subscription_renewed(data)
    elif event_type == "customer.subscription.deleted":
        _on_subscription_cancelled(data)
    elif event_type == "charge.refunded":
        _on_refund(data)

    return {"status": "processed", "event": event_type}


def _on_checkout_complete(session: dict):
    """Full post-sale activation sequence."""
    customer_email = session.get("customer_details", {}).get("email")
    customer_name  = session.get("customer_details", {}).get("name", "")
    amount         = session.get("amount_total", 0) / 100
    product_name   = session.get("metadata", {}).get("product_name", "Unknown Product")
    customer_id    = session.get("customer")

    logger.info(f"New sale: {customer_name} <{customer_email}> — ${amount} — {product_name}")

    # 1. Provision Supabase tenant row
    tenant_id = provision_tenant(
        email=customer_email,
        name=customer_name,
        stripe_customer_id=customer_id,
        product=product_name,
        amount=amount
    )

    # 2. Close deal in HubSpot
    close_deal(
        email=customer_email,
        name=customer_name,
        amount=amount,
        product=product_name
    )

    # 3. Create Linear onboarding project
    linear_project_id = create_onboarding_project(
        client_name=customer_name,
        email=customer_email,
        product=product_name,
        tenant_id=tenant_id
    )

    # 4. Create Notion client workspace
    create_client_workspace(
        name=customer_name,
        email=customer_email,
        product=product_name,
        linear_project_id=linear_project_id,
        tenant_id=tenant_id
    )

    # 5. Send DocuSign contract
    send_contract(
        email=customer_email,
        name=customer_name,
        product=product_name,
        amount=amount
    )

    # 6. Fulfill Shopify order if applicable
    shopify_order_id = session.get("metadata", {}).get("shopify_order_id")
    if shopify_order_id:
        fulfill_order(shopify_order_id)

    logger.info(f"Full activation complete for {customer_email}")


def _on_subscription_renewed(invoice: dict):
    customer_email = invoice.get("customer_email")
    amount = invoice.get("amount_paid", 0) / 100
    logger.info(f"Subscription renewed: {customer_email} — ${amount}")
    # TODO: update Supabase subscription_status, log to Notion ops page


def _on_subscription_cancelled(subscription: dict):
    customer_id = subscription.get("customer")
    logger.info(f"Subscription cancelled: customer={customer_id}")
    # TODO: deprovision tenant in Supabase, update HubSpot deal stage


def _on_refund(charge: dict):
    customer_email = charge.get("billing_details", {}).get("email")
    amount = charge.get("amount_refunded", 0) / 100
    logger.warning(f"Refund issued: {customer_email} — ${amount}")
    # TODO: flag in Supabase, update HubSpot, notify ops via Notion
