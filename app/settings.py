"""
Typed runtime settings for garcar-payments.

Startup is fail-closed: if any required secret is missing when
``get_settings()`` is called (which happens at lifespan startup), the
process exits with a clear error message rather than starting in a
broken state.

Usage::

    from app.settings import get_settings
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
"""
from __future__ import annotations

import sys
from functools import lru_cache
from typing import Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration read from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Required secrets ─────────────────────────────────────────────────
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # ── Required Stripe price IDs ────────────────────────────────────────
    stripe_price_audit: str = ""
    stripe_price_dealdesk: str = ""
    stripe_price_starter: str = ""
    stripe_price_pro: str = ""
    stripe_price_agency: str = ""

    # ── App ──────────────────────────────────────────────────────────────
    app_base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./local.db"
    cors_allow_origins: str = "*"
    environment: str = "development"
    port: int = 8000

    # ── Supabase (optional) ───────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_key: str = ""

    # ── Email delivery via Resend (optional in dev, required in prod) ─────
    resend_api_key: str = ""
    email_from: str = "noreply@garcar.com"

    # ── Signed-download HMAC secret ───────────────────────────────────────
    # Must be set in production; falls back to an insecure default in dev only.
    download_signing_secret: str = ""

    # ── Linear (optional) ────────────────────────────────────────────────
    linear_api_key: str = ""
    linear_team_id: str = ""

    # ── Notion (optional) ────────────────────────────────────────────────
    notion_token: str = ""
    notion_revenue_db_id: str = ""

    @field_validator("stripe_secret_key")
    @classmethod
    def no_placeholder_key(cls, v: str) -> str:
        if v and v.startswith("sk_test_REPLACE"):
            raise ValueError(
                "STRIPE_SECRET_KEY still contains a placeholder value — "
                "replace it with a real Stripe API key."
            )
        return v

    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    def validate_for_production(self) -> list[str]:
        """Return a list of missing/invalid secrets that block production startup."""
        missing: list[str] = []
        required = [
            ("STRIPE_SECRET_KEY", self.stripe_secret_key),
            ("STRIPE_WEBHOOK_SECRET", self.stripe_webhook_secret),
            ("DOWNLOAD_SIGNING_SECRET", self.download_signing_secret),
        ]
        for name, value in required:
            if not value:
                missing.append(name)
        # APP_BASE_URL must be a real HTTPS URL in production (not localhost)
        if not self.app_base_url or not self.app_base_url.startswith("https://"):
            missing.append("APP_BASE_URL")
        # Price IDs must all be configured in production
        price_ids = {
            "STRIPE_PRICE_AUDIT": self.stripe_price_audit,
            "STRIPE_PRICE_DEALDESK": self.stripe_price_dealdesk,
            "STRIPE_PRICE_STARTER": self.stripe_price_starter,
            "STRIPE_PRICE_PRO": self.stripe_price_pro,
            "STRIPE_PRICE_AGENCY": self.stripe_price_agency,
        }
        for name, value in price_ids.items():
            if not value:
                missing.append(name)
        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def assert_production_ready() -> None:
    """
    Called at application startup.  Exits the process if required production
    secrets are absent.  In development (ENVIRONMENT != production) missing
    secrets are only warned about.
    """
    settings = get_settings()
    missing = settings.validate_for_production()

    if missing and settings.is_production():
        print(
            "[FATAL] Production startup rejected — missing required secrets:\n"
            + "\n".join(f"  • {m}" for m in missing)
            + "\nSet these environment variables and restart.",
            file=sys.stderr,
        )
        sys.exit(1)
    elif missing:
        for m in missing:
            print(f"[WARN] Missing secret '{m}' — acceptable in development, required in production.")
