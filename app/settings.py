"""Typed runtime settings for garcar-payments."""
from __future__ import annotations

import os
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.production_guard import production_mode, production_issues


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
        return production_mode(self.environment, os.getenv("VERCEL_ENV", ""))

    def validate_for_production(self) -> list[str]:
        return production_issues(self.model_dump())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def assert_production_ready() -> None:
    settings = get_settings()
    if not settings.is_production():
        return
    issues = settings.validate_for_production()
    if issues:
        raise RuntimeError("Production configuration invalid: " + "; ".join(issues))
