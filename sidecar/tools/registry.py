"""Tool registry: name -> {fn, args_schema, description_tr, timeout}.

Every agent-callable tool is registered here — nothing is ad-hoc. Tools are READ-ONLY
in v1: no tool mutates state, so every loop is safe to retry and every eval reproducible.
Tool descriptions (Turkish) are rendered into the system prompt; a tool description IS
a prompt, so it is versioned next to its implementation.
"""
from __future__ import annotations

import contextvars
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError


@dataclass
class ImageResult:
    """A tool result that must be fed back to the model as an image, not text.

    (e.g. render_page returns a higher-DPI crop for the vision model to re-read.)
    """
    images: list[bytes]
    note_tr: str = ""


class ToolError(Exception):
    """Raised for bad args / unknown tool — fed back to the model as the tool result."""


class ToolTimeout(ToolError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[..., Any]
    args_schema: type[BaseModel]
    description_tr: str
    timeout_s: float


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")

    def register(
        self, name: str, fn: Callable[..., Any], args_schema: type[BaseModel],
        description_tr: str, timeout_s: float = 5.0,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = ToolSpec(name, fn, args_schema, description_tr, timeout_s)

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def specs_for(self, names: list[str]) -> list[ToolSpec]:
        missing = [n for n in names if n not in self._tools]
        if missing:
            raise ValueError(f"unregistered tools requested: {missing}")
        return [self._tools[n] for n in names]

    def describe(self, names: list[str]) -> str:
        """Turkish tool catalogue rendered into the system prompt."""
        lines = []
        for spec in self.specs_for(names):
            props = spec.args_schema.model_json_schema().get("properties", {})
            arg_names = ", ".join(props.keys()) or "-"
            lines.append(f"- {spec.name}({arg_names}): {spec.description_tr}")
        return "\n".join(lines)

    def execute(self, name: str, args: dict[str, Any]) -> Any:
        """Validate args, run under the per-tool timeout, return the result.

        Any failure raises ToolError so call_agent can feed the message back to the
        model (self-correction) and count it as a step — it never crashes the loop.
        """
        spec = self._tools.get(name)
        if spec is None:
            raise ToolError(f"bilinmeyen araç: {name}")
        try:
            validated = spec.args_schema(**(args or {}))
        except ValidationError as e:
            raise ToolError(f"geçersiz argümanlar: {e.errors()}") from e

        # Propagate contextvars (e.g. the active reading document) into the worker thread.
        ctx = contextvars.copy_context()
        future = self._pool.submit(ctx.run, lambda: spec.fn(**validated.model_dump()))
        try:
            return future.result(timeout=spec.timeout_s)
        except FuturesTimeout as e:
            raise ToolTimeout(f"araç zaman aşımına uğradı ({spec.timeout_s}s): {name}") from e
        except ToolError:
            raise
        except Exception as e:  # tool raised -> feed back as a result, never crash the loop
            raise ToolError(f"araç hatası ({name}): {e}") from e


# The single production registry. Empty in Phase 1; real tools self-register per phase
# by importing their module (e.g. tools.page_tools registers render_page/get_page_text).
registry = ToolRegistry()


def summarize_result(result: Any, limit: int = 500) -> str:
    """Compact string form of a tool result for the tool_log + the model's next message."""
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(result)
    return text if len(text) <= limit else text[:limit] + "…"
