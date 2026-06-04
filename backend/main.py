"""
Garcar Enterprise — Unified Payment Engine Entry Point
Mounts: /payments (Stripe webhooks + ledger) + /mars (MARS API checkout)
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.payments import app as payments_app
from backend.mars_tiers import app as mars_app

main_app = FastAPI(
    title="Garcar Enterprise Payment Gateway",
    description="Unified payments: Stripe webhooks, MARS API subscriptions, ledger, Notion CRM",
    version="2.0.0",
)

main_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

main_app.mount("/payments", payments_app)
main_app.mount("/mars", mars_app)


@main_app.get("/")
def root():
    return {
        "service": "Garcar Enterprise Payment Gateway",
        "version": "2.0.0",
        "routes": {
            "mars_landing": "/mars/",
            "mars_checkout": "/mars/checkout/{tier}",
            "mars_tiers_api": "/mars/api/tiers",
            "stripe_webhook": "/payments/webhook/stripe",
            "create_payment_link": "/payments/payment/create-link",
            "mrr_dashboard": "/payments/mrr",
            "health": "/health",
        }
    }


@main_app.get("/health")
def health():
    return {"status": "live", "service": "garcar-payments-gateway", "version": "2.0.0"}


if __name__ == "__main__":
    uvicorn.run(main_app, host="0.0.0.0", port=8000)
