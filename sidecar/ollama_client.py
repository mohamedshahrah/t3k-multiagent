"""Thin wrapper over the Ollama chat API with schema-constrained (JSON) output.

Determinism for reproducible eval: temperature 0 + a fixed seed on every call.
Structured output is enforced via Ollama's `format=<json schema>` (constrained decoding).
"""
from __future__ import annotations

from typing import Any

from ollama import Client
from pydantic import BaseModel

from config import get_settings

_client: Client | None = None
FIXED_SEED = 42


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(host=get_settings().ollama_url)
    return _client


def _attr(obj: Any, key: str) -> Any:
    """Read `key` whether obj is a dict or a pydantic response object (ollama >=0.4)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def chat_json(
    *,
    model: str,
    messages: list[dict[str, Any]],
    schema: type[BaseModel],
    options: dict[str, Any] | None = None,
) -> str:
    """One chat turn whose output is constrained to `schema`. Returns raw JSON text."""
    opts = {"temperature": 0, "seed": FIXED_SEED}
    if options:
        opts.update(options)
    resp = get_client().chat(
        model=model,
        messages=messages,
        format=schema.model_json_schema(),
        options=opts,
    )
    return _attr(_attr(resp, "message"), "content")


def list_models() -> list[str]:
    """Tags currently present in the Ollama volume (for /health and smoke tests)."""
    try:
        data = get_client().list()
        models = _attr(data, "models") or []
        tags = [(_attr(m, "model") or _attr(m, "name")) for m in models]
        return [t for t in tags if t]
    except Exception:
        return []
