"""Single DuckDB connection + a write lock.

DuckDB is an embedded single-writer engine and the sidecar runs one uvicorn worker,
so the whole app shares one connection. Every access goes through the module lock so
async request handlers can never interleave a half-written statement.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import duckdb

from config import get_settings

_conn: duckdb.DuckDBPyConnection | None = None
_lock = threading.RLock()


def get_connection() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                db_path = Path(get_settings().db_path)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                _conn = duckdb.connect(str(db_path))
                _conn.execute("INSTALL json; LOAD json;")
    return _conn


def execute(sql: str, params: list[Any] | tuple[Any, ...] | None = None):
    """Run a statement under the write lock and return the cursor."""
    conn = get_connection()
    with _lock:
        return conn.execute(sql, params) if params is not None else conn.execute(sql)


def query(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[tuple]:
    with _lock:
        return execute(sql, params).fetchall()


def query_dicts(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[dict]:
    """Rows as dicts keyed by column name — convenient for JSON API responses."""
    conn = get_connection()
    with _lock:
        cur = conn.execute(sql, params) if params is not None else conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
