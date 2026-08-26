"""Central config — all API keys loaded from environment variables.
Never hardcode keys. Use Vault or Railway env vars."""
import os

class Config:
    # Stripe
    STRIPE_SECRET_KEY        = os.environ["STRIPE_SECRET_KEY"]
    STRIPE_WEBHOOK_SECRET    = os.environ["STRIPE_WEBHOOK_SECRET"]
    STRIPE_PRICE_IRAS_SETUP  = os.environ.get("STRIPE_PRICE_IRAS_SETUP")
    STRIPE_PRICE_IRAS_MONTHLY= os.environ.get("STRIPE_PRICE_IRAS_MONTHLY")
    STRIPE_PRICE_OPF_AGENCY  = os.environ.get("STRIPE_PRICE_OPF_AGENCY")

    # HubSpot
    HUBSPOT_TOKEN            = os.environ["HUBSPOT_TOKEN"]
    HUBSPOT_PIPELINE_ID      = os.environ.get("HUBSPOT_PIPELINE_ID", "default")
    HUBSPOT_STAGE_NEW        = os.environ.get("HUBSPOT_STAGE_NEW", "appointmentscheduled")
    HUBSPOT_STAGE_CLOSED     = os.environ.get("HUBSPOT_STAGE_CLOSED", "closedwon")

    # Supabase
    SUPABASE_URL             = os.environ["SUPABASE_URL"]
    SUPABASE_SERVICE_KEY     = os.environ["SUPABASE_SERVICE_KEY"]

    # Linear
    LINEAR_API_KEY           = os.environ["LINEAR_API_KEY"]
    LINEAR_TEAM_ID           = os.environ["LINEAR_TEAM_ID"]
    LINEAR_ONBOARDING_TEMPLATE = os.environ.get("LINEAR_ONBOARDING_TEMPLATE_ID")

    # Notion
    NOTION_TOKEN             = os.environ["NOTION_TOKEN"]
    NOTION_CLIENTS_DB        = os.environ["NOTION_CLIENTS_DB_ID"]
    NOTION_OPS_PAGE          = os.environ.get("NOTION_OPS_PAGE_ID")

    # DocuSign
    DOCUSIGN_ACCOUNT_ID      = os.environ["DOCUSIGN_ACCOUNT_ID"]
    DOCUSIGN_ACCESS_TOKEN    = os.environ["DOCUSIGN_ACCESS_TOKEN"]
    DOCUSIGN_TEMPLATE_IRAS   = os.environ["DOCUSIGN_TEMPLATE_IRAS"]
    DOCUSIGN_TEMPLATE_OPF    = os.environ["DOCUSIGN_TEMPLATE_OPF"]

    # Hunter
    HUNTER_API_KEY           = os.environ["HUNTER_API_KEY"]

    # Shopify
    SHOPIFY_STORE_DOMAIN     = os.environ["SHOPIFY_STORE_DOMAIN"]
    SHOPIFY_ADMIN_TOKEN      = os.environ["SHOPIFY_ADMIN_TOKEN"]
    SHOPIFY_WEBHOOK_SECRET   = os.environ.get("SHOPIFY_WEBHOOK_SECRET")

    # Hugging Face
    HF_TOKEN                 = os.environ["HF_TOKEN"]
    HF_MODEL_REPO            = os.environ.get("HF_MODEL_REPO", "Garrettc123/garcar-ops-model")

    # GitHub
    GITHUB_TOKEN             = os.environ["GITHUB_TOKEN"]
    GITHUB_ORG               = os.environ.get("GITHUB_ORG", "Garrettc123")
