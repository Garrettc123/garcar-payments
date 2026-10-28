"""Pure validation helpers; never include credential values in errors."""
from urllib.parse import urlsplit

REQUIRED_FIELDS = (
    "stripe_secret_key", "stripe_webhook_secret", "download_signing_secret",
    "app_base_url", "supabase_url", "supabase_service_key",
    "stripe_price_audit", "stripe_price_dealdesk", "stripe_price_starter",
    "stripe_price_pro", "stripe_price_agency", "database_url",
)

def production_mode(environment, vercel_environment=""):
    return any(str(value).strip().lower() in ("production", "prod")
               for value in (environment, vercel_environment))

def production_issues(values):
    issues = [name.upper() for name in REQUIRED_FIELDS
              if not str(values.get(name) or "").strip()]
    for name in ("app_base_url", "supabase_url"):
        value = str(values.get(name) or "").strip()
        if value:
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            if not valid:
                issues.append(name.upper() + " must be an HTTPS URL without embedded credentials")
    value = str(values.get("database_url") or "").strip()
    if value:
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme == "postgresql+psycopg" and bool(parsed.hostname) and bool(parsed.path.strip("/"))
        except ValueError:
            valid = False
        if not valid:
            issues.append("DATABASE_URL must use postgresql+psycopg with a host and database name")
    return issues
