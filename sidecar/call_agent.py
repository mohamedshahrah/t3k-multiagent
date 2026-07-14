"""THE wrapper. Every LLM call in the system goes through here — no direct Ollama calls.

Two modes, one function:
  * tools=None (or TOOLS_ENABLED=0)  -> single schema-forced call, retry <=2 on bad JSON.
  * tools=[...] and TOOLS_ENABLED=1  -> bounded ReAct loop over the registry, then ONE
    final schema-forced call producing the real Pydantic contract.

The final contract object is identical in both modes. Every step -> a tool_log row;
every call -> an agent_log row (tool_steps, degraded, latency). Loop can never hang the
pipeline: max_steps + per-doc budget + per-tool timeout -> degraded fallback to single-shot.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, create_model

import events
from config import get_settings
from db import repositories as repo
from ids import new_uuid7
from ollama_client import chat_json
from tools.registry import (
    ImageResult, ToolError, ToolRegistry, registry as default_registry, summarize_result,
)

log = logging.getLogger("evrak.agent")

# Per-document tool-call budget counter (in-memory; loops are short-lived).
_budget_used: dict[str, int] = {}


def _forced(schema: type[BaseModel], messages: list[dict], model: str, retries: int = 2):
    """One schema-constrained call with retry-on-invalid-JSON (error fed back to model)."""
    last_err: Exception | None = None
    msgs = list(messages)
    for _ in range(retries + 1):
        raw = chat_json(model=model, messages=msgs, schema=schema)
        try:
            return schema.model_validate_json(raw), raw
        except ValidationError as e:
            last_err = e
            msgs = msgs + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content":
                    f"Çıktı şemaya uymadı. Hatalar: {e.errors()}. Lütfen yalnızca geçerli JSON üret."},
            ]
    raise last_err  # exhausted retries


def _build_agent_step(tool_names: list[str]) -> type[BaseModel]:
    """AgentStep schema whose `action` is a Literal over the allowed tools + 'finish'.

    Constrained decoding then makes an invented tool name literally impossible to emit.
    """
    actions = tuple(tool_names + ["finish"])
    return create_model(
        "AgentStep",
        thought_tr=(str, Field(description="Bu adımda ne yaptığının kısa Türkçe gerekçesi")),
        action=(Literal[actions], Field(description="Çağrılacak araç ya da 'finish'")),
        args=(dict[str, Any], Field(default_factory=dict, description="Aracın argümanları")),
    )


def _user_message(user_content: str, images: list[bytes] | None) -> dict:
    msg: dict[str, Any] = {"role": "user", "content": user_content}
    if images:
        msg["images"] = images
    return msg


def call_agent(
    *,
    agent_name: str,
    system_prompt: str,
    user_content: str,
    schema: type[BaseModel],
    images: list[bytes] | None = None,
    tools: list[str] | None = None,
    max_steps: int | None = None,
    doc_id: str | uuid.UUID | None = None,
    model: str | None = None,
    registry: ToolRegistry | None = None,
) -> BaseModel:
    settings = get_settings()
    model = model or settings.model_tag
    reg = registry or default_registry
    max_steps = max_steps if max_steps is not None else settings.max_tool_steps
    doc_key = str(doc_id) if doc_id else None
    started = time.perf_counter()
    log_id = new_uuid7()

    use_tools = bool(tools) and settings.tools_enabled
    messages = [
        {"role": "system", "content": system_prompt},
        _user_message(user_content, images),
    ]

    tool_steps = 0
    degraded = False

    if use_tools:
        assert tools is not None
        step_schema = _build_agent_step(tools)
        catalogue = reg.describe(tools)
        loop_system = (
            system_prompt
            + "\n\nKullanabileceğin araçlar:\n" + catalogue
            + "\n\nHer adımda TEK bir JSON üret: {thought_tr, action, args}. "
            "Gerekli kanıtı topladığında action=\"finish\" ver; ardından nihai cevap "
            "istenecek. Var olmayan bir aracı çağırma."
        )
        messages[0] = {"role": "system", "content": loop_system}
        events.publish("agent_start", {"doc_id": doc_key, "agent": agent_name})

        for step_no in range(1, max_steps + 1):
            step, _raw = _forced(step_schema, messages, model, retries=1)
            messages.append({"role": "assistant", "content": step.model_dump_json()})

            if step.action == "finish":
                break

            # Per-document tool budget.
            if doc_key is not None and _budget_used.get(doc_key, 0) >= settings.tool_budget_per_doc:
                log.warning("tool budget exhausted for doc %s", doc_key)
                degraded = True
                break

            t0 = time.perf_counter()
            ok = True
            tool_message: dict[str, Any]
            try:
                result = reg.execute(step.action, step.args)
                if isinstance(result, ImageResult):  # feed the image back to the vision model
                    result_summary = result.note_tr or "(görüntü döndürüldü)"
                    tool_message = {"role": "user", "images": result.images,
                                    "content": f"[araç sonucu · {step.action}] {result_summary}"}
                else:
                    result_summary = summarize_result(result)
                    tool_message = {"role": "user",
                                    "content": f"[araç sonucu · {step.action}] {result_summary}"}
            except ToolError as e:  # bad args / unknown / timeout -> self-correction
                ok = False
                result_summary = f"HATA: {e}"
                tool_message = {"role": "user",
                                "content": f"[araç sonucu · {step.action}] {result_summary}"}
            tool_latency = int((time.perf_counter() - t0) * 1000)

            tool_steps += 1
            if doc_key is not None:
                _budget_used[doc_key] = _budget_used.get(doc_key, 0) + 1

            messages.append(tool_message)
            repo.insert_tool_log(
                log_id=new_uuid7(), doc_id=doc_id, agent_log_id=log_id, step_no=step_no,
                tool=step.action, thought_tr=step.thought_tr, args=step.args,
                result_summary=result_summary, ok=ok, latency_ms=tool_latency,
            )
            events.publish("tool_step", {
                "doc_id": doc_key, "agent": agent_name, "step_no": step_no,
                "tool": step.action, "thought_tr": step.thought_tr, "ok": ok,
            })
        else:
            # for-loop finished without `break` -> never emitted finish.
            degraded = True
            log.warning("agent %s exhausted %d steps without finish -> degraded", agent_name, max_steps)

        messages.append({"role": "user", "content":
                         "Artık gerekli bilgiyi topladın. Nihai cevabı istenen şemaya göre üret."})

    # Final (or only) schema-forced call producing the real contract object.
    try:
        result_obj, raw = _forced(schema, messages, model)
    except ValidationError:
        # Last-ditch: retry once fresh, single-shot, no tool history.
        degraded = degraded or use_tools
        result_obj, raw = _forced(
            schema,
            [{"role": "system", "content": system_prompt}, _user_message(user_content, images)],
            model,
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    repo.insert_agent_log(
        log_id=log_id, doc_id=doc_id, agent=agent_name, model=model,
        input_summary=summarize_result(user_content, 300),
        output_summary=summarize_result(raw, 300),
        tool_steps=tool_steps, degraded=degraded, latency_ms=latency_ms,
    )
    if use_tools:
        events.publish("agent_done", {
            "doc_id": doc_key, "agent": agent_name, "tool_steps": tool_steps, "degraded": degraded,
        })
    return result_obj


def reset_budget(doc_id: str | uuid.UUID) -> None:
    _budget_used.pop(str(doc_id), None)
