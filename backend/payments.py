import os, stripe, json, datetime, requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pathlib import Path
import uvicorn
from backend.crypto import (
    sign_contract, holographic_fingerprint, zkp_proof_of_payment,
    hmac_sign, session_id
)

app = FastAPI(title="Garcar Payment Engine")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_REPLACE_ME")
CONTRACTS_DIR = Path("contracts/signed")
CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)

print(f"[BOOT] Garcar Payment Engine | session={session_id()}")

# ── Linear config ──────────────────────────────────────────────────────────────
LINEAR_API_KEY    = os.getenv("LINEAR_API_KEY", "")
LINEAR_TEAM_ID    = os.getenv("LINEAR_TEAM_ID", "0a42fa2d-5df2-45f5-a1c2-1dd78749fe93")
LINEAR_PROJECT_ID = os.getenv("LINEAR_PROJECT_ID", "b403fce1-8b70-4aa1-b5e1-1d48bf0eda4a")
LINEAR_URL        = "https://api.linear.app/graphql"

# ── Notion config ──────────────────────────────────────────────────────────────
NOTION_TOKEN          = os.getenv("NOTION_TOKEN", "")
NOTION_REVENUE_DB_ID  = os.getenv("NOTION_REVENUE_DB_ID",  "0707431dd7594e85956e4340b86e6976")
NOTION_CUSTOMER_DB_ID = os.getenv("NOTION_CUSTOMER_DB_ID", "024f6838e7b745cca1db53db0c4e5fcf")
NOTION_URL            = "https://api.notion.com/v1"
NOTION_VERSION        = "2022-06-28"

# ── Linear state cache ─────────────────────────────────────────────────────────────
_LINEAR_STATE_CACHE: dict[str, str] = {}


# ────────────────────────────────────────────────────────────────────────────
# LINEAR
# ────────────────────────────────────────────────────────────────────────────

def _linear(query: str, variables: dict) -> dict:
    if not LINEAR_API_KEY:
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


def _resolve_linear_state(name_fragment: str) -> str | None:
    key = name_fragment.lower()
    if key in _LINEAR_STATE_CACHE:
        return _LINEAR_STATE_CACHE[key]
    env_map = {
        "in progress": os.getenv("LINEAR_STATE_IN_PROGRESS", ""),
        "at risk":     os.getenv("LINEAR_STATE_AT_RISK", ""),
        "cancelled":   os.getenv("LINEAR_STATE_CANCELLED", ""),
    }
    if env_map.get(key):
        _LINEAR_STATE_CACHE[key] = env_map[key]
        return env_map[key]
    query = """query TeamStates($teamId: String!) {
      team(id: $teamId) { states { nodes { id name type } } }
    }"""
    states = _linear(query, {"teamId": LINEAR_TEAM_ID}).get("team", {}).get("states", {}).get("nodes", [])
    for state in states:
        if key in state["name"].lower() or state["name"].lower() in key:
            _LINEAR_STATE_CACHE[key] = state["id"]
            return state["id"]
    type_map = {"in progress": "started", "at risk": "started", "cancelled": "cancelled"}
    for state in states:
        if state["type"].lower() == type_map.get(key, ""):
            _LINEAR_STATE_CACHE[key] = state["id"]
            return state["id"]
    return None


def _linear_create_issue(title: str, description: str, priority: int = 2) -> dict:
    mutation = """
    mutation IssueCreate($title: String!, $description: String, $teamId: String!, $priority: Int!, $projectId: String) {
      issueCreate(input: { title: $title, description: $description,
        teamId: $teamId, priority: $priority, projectId: $projectId
      }) { success issue { id identifier title url } }
    }"""
    result = _linear(mutation, {
        "title": title, "description": description,
        "teamId": LINEAR_TEAM_ID, "priority": priority,
        "projectId": LINEAR_PROJECT_ID,
    })
    issue = result.get("issueCreate", {}).get("issue", {})
    if issue:
        print(f"[LINEAR] {issue.get('identifier')} — {issue.get('url')}")
    return issue


def _linear_find_issue(subscription_id: str) -> dict | None:
    query = """query IssueSearch($term: String!) {
      issueSearch(query: $term, first: 1) { nodes { id identifier title url } }
    }"""
    nodes = _linear(query, {"term": subscription_id}).get("issueSearch", {}).get("nodes", [])
    return nodes[0] if nodes else None


def _linear_update_state(issue_id: str, state_name: str) -> dict:
    state_id = _resolve_linear_state(state_name)
    if not state_id:
        return {}
    mutation = """mutation IssueUpdate($id: String!, $stateId: String!) {
      issueUpdate(id: $id, input: { stateId: $stateId }) {
        success issue { id identifier state { name } }
      }
    }"""
    return _linear(mutation, {"id": issue_id, "stateId": state_id}).get("issueUpdate", {}).get("issue", {})


# ────────────────────────────────────────────────────────────────────────────
# NOTION
# ────────────────────────────────────────────────────────────────────────────

def _notion_headers() -> dict:
    return {"Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION}

def _notion_create_page(db_id: str, properties: dict) -> dict:
    if not NOTION_TOKEN:
        return {}
    r = requests.post(f"{NOTION_URL}/pages", headers=_notion_headers(),
                      json={"parent": {"database_id": db_id}, "properties": properties}, timeout=15)
    if r.status_code in (200, 201):
        page = r.json()
        print(f"[NOTION] {page.get('url')}")
        return page
    print(f"[NOTION] Error {r.status_code}: {r.text[:200]}")
    return {}

def _notion_query_pages(db_id: str, filter_payload: dict) -> list:
    if not NOTION_TOKEN:
        return []
    r = requests.post(f"{NOTION_URL}/databases/{db_id}/query",
                      headers=_notion_headers(), json={"filter": filter_payload}, timeout=15)
    return r.json().get("results", []) if r.ok else []

def _notion_update_page(page_id: str, properties: dict) -> dict:
    if not NOTION_TOKEN:
        return {}
    r = requests.patch(f"{NOTION_URL}/pages/{page_id}",
                       headers=_notion_headers(), json={"properties": properties}, timeout=15)
    return r.json() if r.ok else {}

def _notion_upsert_customer(subscription_id, customer_id, email, plan, status, mrr, onboarded=None):
    existing = _notion_query_pages(NOTION_CUSTOMER_DB_ID,
        {"property": "Stripe Subscription ID", "rich_text": {"equals": subscription_id}})
    now = datetime.date.today().isoformat()
    props = {
        "Company":                {"title": [{"text": {"content": email}}]},
        "Contact Email":          {"email": email},
        "Stripe Customer ID":     {"rich_text": [{"text": {"content": customer_id}}]},
        "Stripe Subscription ID": {"rich_text": [{"text": {"content": subscription_id}}]},
        "Plan":                   {"select": {"name": plan}},
        "Status":                 {"select": {"name": status}},
        "MRR":                    {"number": round(mrr, 2)},
        "Last Payment":           {"date": {"start": now}},
    }
    if onboarded:
        props["Onboarded"] = {"date": {"start": onboarded}}
    return (_notion_update_page(existing[0]["id"], props) if existing
            else _notion_create_page(NOTION_CUSTOMER_DB_ID, props))

def _notion_log_revenue(mrr, total_payments, status="Live", fingerprint=""):
    now = datetime.datetime.utcnow().isoformat()
    return _notion_create_page(NOTION_REVENUE_DB_ID, {
        "Snapshot":       {"title": [{"text": {"content": f"MRR {now[:16]} | fp:{fingerprint[:8]}"}}]},
        "MRR (USD)":      {"number": round(mrr, 2)},
        "Total Payments": {"number": total_payments},
        "Timestamp":      {"date": {"start": now}},
        "Source":         {"select": {"name": "Stripe"}},
        "Status":         {"select": {"name": status}},
        "Notes":          {"rich_text": [{"text": {"content": f"holographic_fp={fingerprint}"}}]},
    })


# ────────────────────────────────────────────────────────────────────────────
# EVENT HANDLERS
# ────────────────────────────────────────────────────────────────────────────

def _handle_subscription_created(data):
    sub_id    = data["id"]
    customer  = data["customer"]
    status    = data["status"]
    plan_id   = (data.get("items", {}).get("data") or [{}])[0].get("price", {}).get("id", "unknown")
    trial_end = data.get("trial_end")
    trial_note = f"\n- Trial ends: {datetime.datetime.fromtimestamp(trial_end).isoformat()}" if trial_end else ""
    _linear_create_issue(
        title=f"[Stripe] New Subscription: {sub_id}",
        description=(
            f"## New Garcar Subscription\n\n- **Sub:** `{sub_id}`\n"
            f"- **Customer:** `{customer}`\n- **Plan:** `{plan_id}`\n"
            f"- **Status:** `{status}`{trial_note}\n\n"
            f"_Onboard client. Activate DFW lead pipeline._"
        ), priority=2)
    _notion_upsert_customer(sub_id, customer, customer, "DFW Lead Gen",
        "Trial" if trial_end else "Active", 0.0, datetime.date.today().isoformat())

def _handle_invoice_paid(data):
    sub_id   = data.get("subscription")
    email    = data.get("customer_email") or data.get("customer_details", {}).get("email", "unknown")
    amount   = (data.get("amount_paid") or 0) / 100
    customer = data.get("customer", "")
    invoice  = data.get("id", "")
    if not sub_id:
        return

    # Holographic fingerprint: all 3 systems in one atomic hash
    fp = holographic_fingerprint({
        "stripe_subscription": sub_id,
        "stripe_invoice":      invoice,
        "amount_usd":          amount,
        "customer_email":      email,
        "linear_team":         LINEAR_TEAM_ID,
        "notion_customer_db":  NOTION_CUSTOMER_DB_ID,
    })
    print(f"[HOLOGRAPHIC] System fingerprint: {fp}")

    existing = _linear_find_issue(sub_id)
    if existing:
        _linear_update_state(existing["id"], "in progress")
    else:
        _linear_create_issue(
            title=f"[Stripe] Invoice Paid: {sub_id}",
            description=(
                f"## Payment Received\n\n- **Sub:** `{sub_id}`\n"
                f"- **Invoice:** `{invoice}`\n- **Customer:** `{email}`\n"
                f"- **Amount:** `${amount:,.2f}`\n"
                f"- **Fingerprint:** `{fp[:32]}...`\n\n"
                f"_Fulfillment active._"
            ), priority=3)

    _notion_upsert_customer(sub_id, customer, email, "DFW Lead Gen", "Active", amount)
    ledger = Path("logs/ledger.jsonl")
    total, count = 0.0, 0
    if ledger.exists():
        entries = [json.loads(l) for l in ledger.read_text().splitlines() if l]
        total = sum(e["amount_usd"] for e in entries)
        count = len(entries)
    _notion_log_revenue(total, count, fingerprint=fp)

def _handle_payment_failed(data):
    sub_id   = data.get("subscription")
    email    = data.get("customer_email", "unknown")
    customer = data.get("customer", "")
    if not sub_id:
        return
    existing = _linear_find_issue(sub_id)
    if existing:
        _linear_update_state(existing["id"], "at risk")
    else:
        _linear_create_issue(
            title=f"[Stripe] ⚠️ Payment Failed: {sub_id}",
            description=f"## Payment Failed\n\n- **Sub:** `{sub_id}`\n- **Customer:** `{email}`\n\n_Trigger churn prevention agent immediately._",
            priority=1)
    _notion_upsert_customer(sub_id, customer, email, "DFW Lead Gen", "At Risk", 0.0)

def _handle_subscription_deleted(data):
    sub_id   = data["id"]
    customer = data["customer"]
    existing = _linear_find_issue(sub_id)
    if existing:
        _linear_update_state(existing["id"], "cancelled")
    else:
        _linear_create_issue(
            title=f"[Stripe] Cancelled: {sub_id}",
            description=f"## Cancelled\n\n- **Sub:** `{sub_id}`\n- **Customer:** `{customer}`\n\n_Trigger win-back. Pause agents._",
            priority=1)
    _notion_upsert_customer(sub_id, customer, customer, "DFW Lead Gen", "Churned", 0.0)


# ────────────────────────────────────────────────────────────────────────────
# ROUTES
# ────────────────────────────────────────────────────────────────────────────

@app.post("/payment/create-link")
async def create_payment_link(req: Request):
    body = await req.json()
    amount_cents = int(float(body.get("amount_usd", 0)) * 100)
    try:
        price = stripe.Price.create(
            unit_amount=amount_cents, currency="usd",
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
    # HMAC-sign the raw payload for internal integrity logging
    payload_mac = hmac_sign(payload, context="stripe-webhook")
    print(f"[STRIPE] {event_type} | integrity={payload_mac[:16]}...")

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
        email  = data.get("customer_details", {}).get("email", "unknown")
        amount = data.get("amount_total", 0) / 100
        _generate_contract(email, amount)
        _log_payment(email, amount)

    return JSONResponse({"status": "ok", "event": event_type})


@app.get("/state")
def system_state():
    """Holographic system state — fingerprint of all live config in one hash."""
    fp = holographic_fingerprint({
        "linear_team":        LINEAR_TEAM_ID,
        "linear_project":     LINEAR_PROJECT_ID,
        "notion_revenue_db":  NOTION_REVENUE_DB_ID,
        "notion_customer_db": NOTION_CUSTOMER_DB_ID,
        "session":            session_id(),
    })
    return {"holographic_fingerprint": fp, "session": session_id(), "service": "garcar-payments"}


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
    return {"status": "running", "service": "garcar-payments", "session": session_id()}


# ── HELPERS ─────────────────────────────────────────────────────────────────────────

def _generate_contract(email: str, amount: float):
    now   = datetime.datetime.now().strftime("%Y-%m-%d")
    text  = "\n".join([
        "SERVICE AGREEMENT", "",
        f"Date: {now}", f"Client: {email}",
        "Provider: Garcar Enterprise LLC",
        f"Amount: ${amount:,.2f}", "",
        "Scope: AI-powered lead generation, automated follow-up,",
        "proposal delivery, and revenue closure for DFW contractors.", "",
        "Payment constitutes acceptance of services rendered.",
        "Binding upon receipt of cleared funds.", "",
        "Garcar Enterprise LLC - Grandview, TX",
    ])
    # Ed25519 sign the contract
    sig_data = sign_contract(text)
    sig_json = json.dumps(sig_data, indent=2)

    out = CONTRACTS_DIR / f"contract_{email.replace('@','_')}_{now}.txt"
    out.write_text(text + f"\n\n--- CRYPTOGRAPHIC SIGNATURE ---\n{sig_json}\n")
    print(f"[CONTRACT] Signed & saved: {out}")


def _log_payment(email: str, amount: float):
    ledger = Path("logs/ledger.jsonl")
    entry  = {"ts": datetime.datetime.now().isoformat(), "email": email, "amount_usd": amount}
    with open(ledger, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[LEDGER] +${amount} from {email}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8007)
