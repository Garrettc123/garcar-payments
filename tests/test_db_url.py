import pytest
from sqlalchemy import create_engine, text

from app.db import resolve_database_url


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("DATABASE_URL", "VERCEL", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(k, raising=False)


def test_postgres_urls_use_psycopg3(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/d")
    assert resolve_database_url() == "postgresql+psycopg://u:p@h:5432/d"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    assert resolve_database_url() == "postgresql+psycopg://u:p@h:5432/d"


def test_explicit_driver_url_untouched(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/d")
    assert resolve_database_url() == "postgresql+psycopg://u:p@h/d"


def test_serverless_without_database_url_uses_tmp(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert resolve_database_url() == "sqlite:////tmp/garcar_payments.db"


def test_serverless_fallback_url_is_connectable(monkeypatch, tmp_path):
    """The fallback must not depend on the (read-only) working directory."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "fn")
    monkeypatch.chdir(tmp_path)
    engine = create_engine(resolve_database_url())
    with engine.begin() as conn:
        assert conn.execute(text("select 1")).scalar() == 1


def test_local_default(monkeypatch):
    assert resolve_database_url() == "sqlite:///./local.db"
