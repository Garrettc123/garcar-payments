import os, stripe, json, datetime, requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pathlib import Path
import uvicorn

app = FastAPI(title="Garcar Payment Engine")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_REPLACE_ME")
CONTRACTS_DIR = Path("contracts/signed")
CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Linear config ──────────────────────────────────────────────────────────────
LINEAR_API_KEY    = os.getenv("LINEAR_API_KEY", "")
LINEAR_TEAM_ID    = os.getenv("LINEAR_TEAM_ID", "0a42fa2d-5df2-45f5-a1c2-1dd78749fe93")
LINEAR_PROJECT_ID = os.getenv("LINEAR_PROJECT_ID", "b403fce1-8b70-4aa1-b5e1-1d48bf0eda4a")
LINEAR_URL        = "https://api.linear.app/graphql"

def _linear(query: str, variables: dict) -> dict:
    """Execute a Linear GraphQL mutation or query."""
    if not LINEAR_API_KEY:
        print("[LINEAR] No API key set — skipping")
        return {}
    r = requests.post(
        LINEAR_URL,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINEAR_API_KEY}"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        print("[LINEAR] GraphQL errors:", data["errors"])
    return data.get("data", {})

def _linear_create_issue(title: str, description: str, priority: int = 2) -> dict:
    mutation = """
    mutation IssueCreate($title: String!, $description: String, $teamId: String!, $priority: Int!, $projectId: String) {
      issueCreate(input: {
        title: $title, description: $description,
        teamId: $teamId, priority: $priority, projectId: $projectId
      }) {
        success
        issue { id identifier title url }
      }
    }
    """
    result = _linear(mutation, {
        "title": title, "description": description,
        "teamId": LINEAR_TEAM_ID, "priority": priority,
        "projectId": LINEAR_PROJECT_ID,
    })
    issue = result.get("issueCreate", {}).get("issue", {})
    if issue:
        print(f"[LINEAR] Created issue {issue.get('identifier')} — {issue.get('url')}")
    return issue

def _linear_find_issue(subscription_id: str) -> dict | None:
    query = """
    query IssueSearch($term: String!) {
      issueSearch(query: $term, first: 1) {
        nodes { id identifier title url }
      }
    }
    """
    nodes = _linear(query, {"term": subscription_id}).get("issueSearch", {}).get("nodes", [])
    return nodes[0] if nodes else None

def _linear_update_state(issue_id: str, state_id: str) -> dict:
    mutation = """
    mutation IssueUpdate($id: String!, $stateId: String!) {
      issueUpdate(id: $id, input: { stateId: $stateId }) {
        success
        issue { id identifier title state { name } }
      }
    }
    """
    result = _linear(mutation, {"id": issue_id, "stateId": state_id})
    issue = result.get("issueUpdate", {}).get("issue", {})
    if issue:
        print(f"[LINEAR] Updated {issue.get('identifier')} → {issue.get('state', {}).get('name')}")
    return issue

# Linear state IDs — set these in your env or replace with real state IDs from your workspace
LINEAR_STATE_IN_PROGRESS = os.getenv("LINEAR_STATE_IN_PROGRESS", "")
LINEAR_STATE_AT_RISK      = os.getenv("LINEAR_STATE_AT_RISK", "")
LINEAR_STATE_CANCELLED    = os.getenv("LINEAR_STATE_CANCELLED", "")


# ── Stripe event → Linear mapping ─────────────────────────────────────────────
def _handle_subscription_created(data: dict):
    sub_id     = data["id"]
    customer   = data["customer"]
    status     = data["status"]
    plan_id    = (data.get("items", {}).get("data") or [{}])[0].get("price", {}).get("id", "unknown")
    trial_end  = data.get("trial_end")
    trial_note = f"\n- Trial ends: {datetime.datetime.fromtimestamp(trial_end).isoformat()}" if trial_end else ""

    issue = _linear_create_issue(
        title=f"[Stripe] New Subscription: {sub_id}",
        description=(
            f"## New Garcar Enterprise Subscription\n\n"
            f"- **Subscription ID:** `{sub_id}`\n"
            f"- **Customer ID:** `{customer}`\n"
            f"- **Plan:** `{plan_id}`\n"
            f"- **Status:** `{status}`{trial_note}\n\n"
            f"_Fulfillment required: onboard client, configure outreach agents, confirm DFW lead pipeline active._"
        ),
        priority=2,
    )
    return issue

def _handle_invoice_paid(data: dict):
    sub_id  = data.get("subscription")
    email   = data.get("customer_email", "unknown")
    amount  = (data.get("amount_paid") or 0) / 100
    invoice = data.get("id")
    if not sub_id:
        return

    existing = _linear_find_issue(sub_id)
    if existing and LINEAR_STATE_IN_PROGRESS:
        _linear_update_state(existing["id"], LINEAR_STATE_IN_PROGRESS)
        print(f"[LINEAR] invoice.paid → moved {existing['identifier']} to In Progress")
    else:
        _linear_create_issue(
            title=f"[Stripe] Invoice Paid: {sub_id}",
            description=(
                f"## Payment Received\n\n"
                f"- **Subscription ID:** `{sub_id}`\n"
                f"- **Invoice:** `{invoice}`\n"
                f"- **Customer:** `{email}`\n"
                f"- **Amount:** `${amount:,.2f}`\n\n"
                f"_Fulfillment active — revenue agents running._"
            ),
            priority=3,
        )

def _handle_payment_failed(data: dict):
    sub_id = data.get("subscription")
    email  = data.get("customer_email", "unknown")
    if not sub_id:
        return
    existing = _linear_find_issue(sub_id)
    if existing and LINEAR_STATE_AT_RISK:
        _linear_update_state(existing["id"], LINEAR_STATE_AT_RISK)
    else:
        _linear_create_issue(
            title=f"[Stripe] ⚠️ Payment Failed: {sub_id}",
            description=(
                f"## Payment Failed — Action Required\n\n"
                f"- **Subscription ID:** `{sub_id}`\n"
                f"- **Customer:** `{email}`\n\n"
                f"_Trigger churn prevention agent. Contact customer immediately._"
            ),
            priority=1,
        )

def _handle_subscription_deleted(data: dict):
    sub_id   = data["id"]
    customer = data["customer"]
    existing = _linear_find_issue(sub_id)
    if existing and LINEAR_STATE_CANCELLED:
        _linear_update_state(existing["id"], LINEAR_STATE_CANCELLED)
    else:
        _linear_create_issue(
            title=f"[Stripe] Cancelled: {sub_id}",
            description=(
                f"## Subscription Cancelled\n\n"
                f"- **Subscription ID:** `{sub_id}`\n"
                f"- **Customer ID:** `{customer}`\n\n"
                f"_Trigger win-back sequence. Pause all fulfillment agents for this customer._"
            ),
            priority=1,
        )


# ── Routes ─────────────────────────────────────────────────────────────────────
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
    payload    = await req.body()
    sig_header = req.headers.get("stripe-signature", "")
    secret     = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_REPLACE_ME")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]
    data       = event["data"]["object"]
    print(f"[STRIPE] Received event: {event_type}")

    # ── Subscription lifecycle → Linear ───────────────────────────────────────
    if event_type == "customer.subscription.created":
        _handle_subscription_created(data)

    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data)

    elif event_type == "invoice.paid":
        email  = data.get("customer_details", {}).get("email") or data.get("customer_email", "unknown")
        amount = data.get("amount_paid", 0) / 100
        _generate_contract(email, amount)
        _log_payment(email, amount)
        _handle_invoice_paid(data)

    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data)

    elif event_type == "checkout.session.completed":
        session = data
        email   = session.get("customer_details", {}).get("email", "unknown")
        amount  = session.get("amount_total", 0) / 100
        _generate_contract(email, amount)
        _log_payment(email, amount)

    return JSONResponse({"status": "ok", "event": event_type})


# ── Helpers ────────────────────────────────────────────────────────────────────
def _generate_contract(email: str, amount: float):
    now   = datetime.datetime.now().strftime("%Y-%m-%d")
    lines = [
        "SERVICE AGREEMENT", "",
        "Date: " + now,
        "Client: " + email,
        "Provider: Garcar Enterprise LLC",
        "Amount: $" + f"{amount:,.2f}", "",
        "Scope: AI-powered lead generation, automated follow-up,",
        "proposal delivery, and revenue closure for DFW contractors.", "",
        "Payment constitutes acceptance of services rendered.",
        "Binding upon receipt of cleared funds.", "",
        "Garcar Enterprise LLC - Grandview, TX",
    ]
    out = CONTRACTS_DIR / ("contract_" + email.replace("@", "_") + "_" + now + ".txt")
    out.write_text("\n".join(lines))
    print("[CONTRACT] " + str(out))

def _log_payment(email: str, amount: float):
    ledger = Path("logs/ledger.jsonl")
    entry  = {"ts": datetime.datetime.now().isoformat(), "email": email, "amount_usd": amount}
    with open(ledger, "a") as f:
        f.write(json.dumps(entry) + "\n")
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
