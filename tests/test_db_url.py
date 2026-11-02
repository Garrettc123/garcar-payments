import importlib

import pytest


def _reload(monkeypatch, **env):
    for k in ("DATABASE_URL", "VERCEL", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.db as db
    return importlib.reload(db)


def test_postgres_urls_use_psycopg3(monkeypatch):
    db = _reload(monkeypatch, DATABASE_URL="postgres://u:p@h:5432/d")
    assert db.resolve_database_url() == "postgresql+psycopg://u:p@h:5432/d"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    assert db.resolve_database_url() == "postgresql+psycopg://u:p@h:5432/d"


def test_explicit_driver_url_untouched(monkeypatch):
    db = _reload(monkeypatch, DATABASE_URL="postgresql+psycopg://u:p@h/d")
    assert db.resolve_database_url() == "postgresql+psycopg://u:p@h/d"


def test_serverless_without_database_url_uses_tmp(monkeypatch):
    db = _reload(monkeypatch, VERCEL="1")
    assert db.resolve_database_url() == "sqlite:////tmp/garcar_payments.db"


def test_serverless_boot_on_readonly_cwd(monkeypatch, tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    monkeypatch.chdir(ro)
    db = _reload(monkeypatch, VERCEL="1")
    db.init_db()  # previously: sqlite3.OperationalError: unable to open database file


def test_local_default(monkeypatch):
    db = _reload(monkeypatch)
    assert db.resolve_database_url() == "sqlite:///./local.db"
