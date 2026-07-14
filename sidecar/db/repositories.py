"""Thin data-access helpers. All SQL lives here so callers never write raw queries.

JSON columns are passed as Python objects and serialized here (``?::JSON``); on read
they come back as JSON text and are parsed here, so callers only ever see Python dicts.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from db.connection import execute, query_dicts


# --- serialization helpers -------------------------------------------------
def _j(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _parse_json_fields(row: dict, fields: tuple[str, ...]) -> dict:
    for f in fields:
        if f in row and isinstance(row[f], str):
            try:
                row[f] = json.loads(row[f])
            except (ValueError, TypeError):
                pass
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            row[k] = str(v)
    return row


# --- documents -------------------------------------------------------------
def get_document_by_sha(sha256: str) -> dict | None:
    rows = query_dicts("SELECT * FROM documents WHERE sha256 = ?", [sha256])
    return rows[0] if rows else None


def insert_document(
    *, doc_id: uuid.UUID, sha256: str, filename: str, mime: str,
    source_path: str, page_count: int, is_scanned: bool, status: str,
) -> None:
    execute(
        "INSERT INTO documents (id, sha256, filename, mime, source_path, "
        "page_count, is_scanned, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [doc_id, sha256, filename, mime, source_path, page_count, is_scanned, status],
    )


def get_document(doc_id: str) -> dict | None:
    rows = query_dicts("SELECT * FROM documents WHERE id = CAST(? AS UUID)", [doc_id])
    return _parse_json_fields(rows[0], ()) if rows else None


def list_documents() -> list[dict]:
    rows = query_dicts(
        "SELECT id, filename, mime, page_count, is_scanned, status, received_at "
        "FROM documents ORDER BY received_at DESC"
    )
    return [_parse_json_fields(r, ()) for r in rows]


def set_status(doc_id: uuid.UUID | str, status: str) -> None:
    execute("UPDATE documents SET status = ? WHERE id = CAST(? AS UUID)", [status, str(doc_id)])


def set_raw_text(doc_id: uuid.UUID | str, raw_text: str) -> None:
    execute("UPDATE documents SET raw_text = ? WHERE id = CAST(? AS UUID)", [raw_text, str(doc_id)])


# --- pages -----------------------------------------------------------------
def upsert_page(
    *, doc_id: uuid.UUID | str, page_no: int, text: str | None = None,
    image_path: str | None = None, has_signature: bool | None = None,
    has_stamp: bool | None = None,
) -> None:
    """Insert or replace a page row (delete-then-insert keeps it simple in DuckDB)."""
    execute(
        "DELETE FROM pages WHERE doc_id = CAST(? AS UUID) AND page_no = ?",
        [str(doc_id), page_no],
    )
    execute(
        "INSERT INTO pages (doc_id, page_no, text, image_path, has_signature, has_stamp) "
        "VALUES (CAST(? AS UUID), ?, ?, ?, ?, ?)",
        [str(doc_id), page_no, text, image_path, has_signature, has_stamp],
    )


def get_pages(doc_id: str) -> list[dict]:
    return query_dicts(
        "SELECT page_no, text, image_path, has_signature, has_stamp "
        "FROM pages WHERE doc_id = CAST(? AS UUID) ORDER BY page_no",
        [doc_id],
    )


# --- classifications / summaries / validations (read side for the detail view) ---
def get_classification(doc_id: str) -> dict | None:
    rows = query_dicts("SELECT * FROM classifications WHERE doc_id = CAST(? AS UUID)", [doc_id])
    return _parse_json_fields(rows[0], ("entities",)) if rows else None


def get_summary(doc_id: str) -> dict | None:
    rows = query_dicts("SELECT * FROM summaries WHERE doc_id = CAST(? AS UUID)", [doc_id])
    return rows[0] if rows else None


def get_validation(doc_id: str) -> dict | None:
    rows = query_dicts("SELECT * FROM validations WHERE doc_id = CAST(? AS UUID)", [doc_id])
    return _parse_json_fields(rows[0], ("missing_fields", "matched_rules")) if rows else None


# --- agent_log / tool_log (the reasoning trace) ----------------------------
def insert_agent_log(
    *, log_id: uuid.UUID, doc_id: uuid.UUID | str | None, agent: str, model: str,
    input_summary: str, output_summary: str, tool_steps: int, degraded: bool, latency_ms: int,
) -> None:
    execute(
        "INSERT INTO agent_log (id, doc_id, agent, model, input_summary, output_summary, "
        "tool_steps, degraded, latency_ms) VALUES (?, CAST(? AS UUID), ?, ?, ?, ?, ?, ?, ?)",
        [log_id, str(doc_id) if doc_id else None, agent, model,
         input_summary, output_summary, tool_steps, degraded, latency_ms],
    )


def insert_tool_log(
    *, log_id: uuid.UUID, doc_id: uuid.UUID | str | None, agent_log_id: uuid.UUID,
    step_no: int, tool: str, thought_tr: str, args: Any, result_summary: str,
    ok: bool, latency_ms: int,
) -> None:
    execute(
        "INSERT INTO tool_log (id, doc_id, agent_log_id, step_no, tool, thought_tr, args, "
        "result_summary, ok, latency_ms) VALUES "
        "(?, CAST(? AS UUID), ?, ?, ?, ?, ?::JSON, ?, ?, ?)",
        [log_id, str(doc_id) if doc_id else None, agent_log_id, step_no, tool,
         thought_tr, _j(args), result_summary, ok, latency_ms],
    )


def get_trace(doc_id: str) -> dict:
    agents = query_dicts(
        "SELECT * FROM agent_log WHERE doc_id = CAST(? AS UUID) ORDER BY ts", [doc_id]
    )
    tools = query_dicts(
        "SELECT * FROM tool_log WHERE doc_id = CAST(? AS UUID) ORDER BY ts, step_no", [doc_id]
    )
    for t in tools:
        _parse_json_fields(t, ("args",))
    for a in agents:
        _parse_json_fields(a, ())
    return {"agent_log": agents, "tool_log": tools}
