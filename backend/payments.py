import os, stripe, json, datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pathlib import Path
import uvicorn

app = FastAPI(title="Garcar Payment Engine")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_REPLACE_ME")
CONTRACTS_DIR = Path("contracts/signed")
CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/payment/create-link")
async def create_payment_link(req: Request):
    body = await req.json()
    amount_cents = int(float(body.get("amount_usd", 0)) * 100)
    try:
        price = stripe.Price.create(
            unit_amount=amount_cents,
            currency="usd",
            product_data={"name": body.get("description", "Garcar Services")},
        )
        link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            after_completion={"type": "redirect",
                              "redirect": {"url": "https://garcarenterprise.com/thank-you"}},
        )
        return {"payment_url": link.url, "amount_usd": body.get("amount_usd")}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhook/stripe")
async def stripe_webhook(req: Request):
    payload = await req.body()
    sig_header = req.headers.get("stripe-signature", "")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_REPLACE_ME")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_details", {}).get("email", "unknown")
        amount = session.get("amount_total", 0) / 100
        _generate_contract(email, amount)
        _log_payment(email, amount)
    return JSONResponse({"status": "ok"})

def _generate_contract(email: str, amount: float):
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    lines = [
        "SERVICE AGREEMENT",
        "",
        "Date: " + now,
        "Client: " + email,
        "Provider: Garcar Enterprise LLC",
        "Amount: $" + f"{amount:,.2f}",
        "",
        "Scope: AI-powered lead generation, automated follow-up,",
        "proposal delivery, and revenue closure for DFW contractors.",
        "",
        "Payment constitutes acceptance of services rendered.",
        "Binding upon receipt of cleared funds.",
        "",
        "Garcar Enterprise LLC - Grandview, TX",
    ]
    out = CONTRACTS_DIR / ("contract_" + email.replace("@","_") + "_" + now + ".txt")
    out.write_text("".join(lines))
    print("[CONTRACT] " + str(out))

def _log_payment(email: str, amount: float):
    ledger = Path("logs/ledger.jsonl")
    entry = {"ts": datetime.datetime.now().isoformat(), "email": email, "amount_usd": amount}
    with open(ledger, "a") as f:
        f.write(json.dumps(entry) + "")
    print("[LEDGER] +$" + str(amount) + " from " + email)

@app.get("/mrr")
def get_mrr():
    ledger = Path("logs/ledger.jsonl")
    if not ledger.exists():
        return {"mrr_usd": 0, "total_payments": 0}
    entries = [json.loads(l) for l in ledger.read_text().splitlines() if l]
    return {"mrr_usd": round(sum(e["amount_usd"] for e in entries), 2),
            "total_payments": len(entries)}

@app.get("/health")
def health():
    return {"status": "running", "service": "garcar-payments"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8007)
