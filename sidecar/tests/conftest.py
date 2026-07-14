"""Test fixtures: a throwaway DuckDB per test so repositories run for real."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("RULES_PATH", str(tmp_path / "rules"))
    monkeypatch.setenv("TOOLS_ENABLED", "1")

    from config import get_settings
    get_settings.cache_clear()
    import db.connection as conn
    conn._conn = None

    from db.migrate import run_migrations
    run_migrations()
    yield

    conn._conn = None
    get_settings.cache_clear()
