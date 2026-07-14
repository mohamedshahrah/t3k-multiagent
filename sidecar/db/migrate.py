"""Plain numbered-.sql migration runner, applied in order at startup.

Each file in migrations/ is applied exactly once and recorded in schema_migrations.
No ORM, no external migration tool — the file list *is* the schema history.
"""
from __future__ import annotations

import logging
from pathlib import Path

from db.connection import execute, get_connection

log = logging.getLogger("evrak.migrate")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _applied_versions() -> set[str]:
    execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT now())"
    )
    return {row[0] for row in get_connection().execute("SELECT version FROM schema_migrations").fetchall()}


def run_migrations() -> list[str]:
    """Apply every pending migration in filename order. Returns the ones applied."""
    applied = _applied_versions()
    newly: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem  # e.g. "001_init"
        if version in applied:
            continue
        log.info("applying migration %s", version)
        sql = path.read_text(encoding="utf-8")
        # DuckDB executes multi-statement scripts; wrap in a transaction for atomicity.
        execute("BEGIN TRANSACTION")
        try:
            get_connection().execute(sql)
            execute("INSERT INTO schema_migrations (version) VALUES (?)", [version])
            execute("COMMIT")
        except Exception:
            execute("ROLLBACK")
            raise
        newly.append(version)
    return newly


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("applied:", run_migrations() or "nothing (up to date)")
