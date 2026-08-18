"""Typed runtime settings for garcar-payments."""
from __future__ import annotations

import sys
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_audit: str = ""
    stripe_price_dealdesk: str = ""
    stripe_price_starter: str = ""
    stripe_price_pro: str = ""
    stripe_price_agency: str = ""
    app_base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./local.db"
    cors_allow_origins: str = "*"
    environment: str = "development"
    port: int = 8000

    supabase_url: str = ""
    supabase_service_key: str = ""
    resend_api_key: str = ""
    email_from: str = "noreply@garcar.com"
    download_signing_secret: str = ""

    linear_api_key: str = ""
    linear_team_id: str = ""
    notion_token: str = ""
    notion_revenue_db_id: str = ""
    hubspot_access_token: str = ""
    asana_access_token: str = ""
    asana_workspace_gid: str = ""

    @field_validator("stripe_secret_key")
    @classmethod
    def no_placeholder_key(cls, v: str) -> str:
        if v and v.startswith("sk_test_REPLACE"):
            raise ValueError("STRIPE_SECRET_KEY still contains a placeholder value")
        return v

    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    def validate_for_production(self) -> list[str]:
        required = [
            ("STRIPE_SECRET_KEY", self.stripe_secret_key),
            ("STRIPE_WEBHOOK_SECRET", self.stripe_webhook_secret),
            ("DOWNLOAD_SIGNING_SECRET", self.download_signing_secret),
            ("APP_BASE_URL", self.app_base_url if self.app_base_url.startswith("https://") else ""),
            ("HUBSPOT_ACCESS_TOKEN", self.hubspot_access_token),
            ("ASANA_ACCESS_TOKEN", self.asana_access_token),
            ("ASANA_WORKSPACE_GID", self.asana_workspace_gid),
            ("SUPABASE_URL", self.supabase_url),
            ("SUPABASE_SERVICE_KEY", self.supabase_service_key),
            ("NOTION_TOKEN", self.notion_token),
            ("NOTION_REVENUE_DB_ID", self.notion_revenue_db_id),
            ("LINEAR_API_KEY", self.linear_api_key),
            ("LINEAR_TEAM_ID", self.linear_team_id),
        ]
        missing = [name for name, value in required if not value]
        for name, value in {
            "STRIPE_PRICE_AUDIT": self.stripe_price_audit,
            "STRIPE_PRICE_DEALDESK": self.stripe_price_dealdesk,
            "STRIPE_PRICE_STARTER": self.stripe_price_starter,
            "STRIPE_PRICE_PRO": self.stripe_price_pro,
            "STRIPE_PRICE_AGENCY": self.stripe_price_agency,
        }.items():
            if not value:
                missing.append(name)
        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def assert_production_ready() -> None:
    settings = get_settings()
    missing = settings.validate_for_production()
    if missing and settings.is_production():
        print("[FATAL] Production startup rejected — missing required secrets:\n" + "\n".join(f"  - {m}" for m in missing), file=sys.stderr)
        sys.exit(1)
    for name in missing:
        print(f"[WARN] Missing secret '{name}' — required in production.")
