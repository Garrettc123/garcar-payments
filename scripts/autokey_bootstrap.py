import os
import sys
import secrets
import json
import subprocess
import urllib.request
import urllib.error
import urllib.parse

def run_cmd(cmd):
    print(f\"> {' '.join(cmd)}\")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f\"Command failed: {cmd}\")

def call_stripe(endpoint, method=\"GET\", data=None):
    url = f\"https://api.stripe.com/v1/{endpoint}\"
    req = urllib.request.Request(url, method=method)
    req.add_header(\"Authorization\", f\"Bearer {os.environ['STRIPE_SECRET_KEY']}\")
    if data:
        encoded = urllib.parse.urlencode(data).encode(\"utf-8\")
        req.data = encoded
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f\"Stripe API error on {endpoint}: {e.read().decode()}\")

def ensure_product(name, amount_cents, mode):
    res = call_stripe(\"products/search?query=name:'\" + urllib.parse.quote(name) + \"'\")
    if res.get(\"data\"):
        prod_id = res[\"data\"][0][\"id\"]
        print(f\"[+] Found existing product '{name}': {prod_id}\")
    else:
        print(f\"[+] Creating product '{name}'...\")
        prod = call_stripe(\"products\", method=\"POST\", data={\"name\": name})
        prod_id = prod[\"id\"]
        
        price_data = {
            \"product\": prod_id,
            \"currency\": \"usd\",
            \"unit_amount\": amount_cents,
        }
        if mode == \"subscription\":
            price_data[\"recurring[interval]\"] = \"month\"
        
        price = call_stripe(\"prices\", method=\"POST\", data=price_data)
        print(f\"    Created price: {price['id']}\")
        return price[\"id\"]
        
    prices = call_stripe(f\"prices?product={prod_id}&active=true\")
    if prices.get(\"data\"):
        return prices[\"data\"][0][\"id\"]
    return None

def main():
    if not os.environ.get(\"STRIPE_SECRET_KEY\"):
        sys.exit(\"Missing STRIPE_SECRET_KEY\")
    if not os.environ.get(\"RAILWAY_TOKEN\"):
        sys.exit(\"Missing RAILWAY_TOKEN\")

    print(\"=== Garcar AutoKey Bootstrap ===\")
    
    price_audit = ensure_product(\"Operational Audit\", 19700, \"payment\")
    price_dealdesk = ensure_product(\"AI Deal Desk Setup\", 49700, \"payment\")
    price_starter = ensure_product(\"Starter Automation\", 99700, \"subscription\")
    price_pro = ensure_product(\"Pro Automation\", 249700, \"subscription\")
    price_agency = ensure_product(\"Agency Automation\", 499700, \"subscription\")
    
    app_url = os.environ.get(\"APP_BASE_URL\", \"https://garcar-payments.up.railway.app\")
    webhook_url = f\"{app_url}/stripe-webhook\"
    
    print(f\"[+] Ensuring Webhook for {webhook_url}\")
    endpoints = call_stripe(\"webhook_endpoints\")
    wh_secret = None
    for ep in endpoints.get(\"data\", []):
        if ep[\"url\"] == webhook_url:
            print(f\"    Found existing webhook. Deleting to regenerate secret...\")
            call_stripe(f\"webhook_endpoints/{ep['id']}\", method=\"DELETE\")
            break
            
    print(\"    Creating new webhook endpoint...\")
    wh = call_stripe(\"webhook_endpoints\", method=\"POST\", data={
        \"url\": webhook_url,
        \"enabled_events[0]\": \"checkout.session.completed\",
        \"enabled_events[1]\": \"invoice.paid\",
    })
    wh_secret = wh[\"secret\"]
        
    signing_secret = secrets.token_hex(32)
    
    print(\"[+] Pushing secrets to Railway...\")
    secrets_map = {
        \"STRIPE_SECRET_KEY\": os.environ[\"STRIPE_SECRET_KEY\"],
        \"STRIPE_WEBHOOK_SECRET\": wh_secret,
        \"DOWNLOAD_SIGNING_SECRET\": signing_secret,
        \"STRIPE_PRICE_AUDIT\": price_audit,
        \"STRIPE_PRICE_DEALDESK\": price_dealdesk,
        \"STRIPE_PRICE_STARTER\": price_starter,
        \"STRIPE_PRICE_PRO\": price_pro,
        \"STRIPE_PRICE_AGENCY\": price_agency,
        \"APP_BASE_URL\": app_url,
        \"ENVIRONMENT\": \"production\",
    }
    
    for k, v in secrets_map.items():
        if v:
            run_cmd([\"railway\", \"variables\", \"set\", f\"{k}={v}\"])
            
    print(\"[+] AutoKey sync complete. Triggering redeploy...\")
    run_cmd([\"railway\", \"redeploy\"])

if __name__ == \"__main__\":
    main()