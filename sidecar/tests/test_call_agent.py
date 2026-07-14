"""Proves the call_agent tool loop machinery with a dummy tool and a mocked LLM.

No model/Ollama needed: we script chat_json's responses so the test is deterministic.
This is the Phase-1 "Done when" check for the wrapper.
"""
from __future__ import annotations

from pydantic import BaseModel

import call_agent as ca
from schemas import SimpleAnswer
from tools.registry import ToolRegistry


class _NoArgs(BaseModel):
    pass


def _registry_with_clock() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        "get_current_time", lambda: "2026-07-12T10:00:00", _NoArgs,
        description_tr="Şu anki zamanı döndürür", timeout_s=2.0,
    )
    return reg


def test_tool_loop_calls_tool_then_finishes(monkeypatch):
    reg = _registry_with_clock()
    seq = {"n": 0}

    def fake_chat_json(*, model, messages, schema, options=None):
        if schema.__name__ == "AgentStep":
            seq["n"] += 1
            if seq["n"] == 1:
                return '{"thought_tr":"zamanı öğren","action":"get_current_time","args":{}}'
            return '{"thought_tr":"yeterli bilgi var","action":"finish","args":{}}'
        return '{"answer_tr":"Şu an saat 10:00"}'  # final SimpleAnswer

    monkeypatch.setattr(ca, "chat_json", fake_chat_json)

    out = ca.call_agent(
        agent_name="test", system_prompt="Sen bir test ajanısın.",
        user_content="Saat kaç?", schema=SimpleAnswer,
        tools=["get_current_time"], registry=reg, doc_id=None,
    )

    assert isinstance(out, SimpleAnswer)
    assert out.answer_tr == "Şu an saat 10:00"
    assert seq["n"] == 2  # one tool step + one finish


def test_tools_disabled_falls_back_to_single_shot(monkeypatch):
    monkeypatch.setenv("TOOLS_ENABLED", "0")
    from config import get_settings
    get_settings.cache_clear()

    reg = _registry_with_clock()
    seen_schemas: list[str] = []

    def fake_chat_json(*, model, messages, schema, options=None):
        seen_schemas.append(schema.__name__)
        return '{"answer_tr":"tek atış cevabı"}'

    monkeypatch.setattr(ca, "chat_json", fake_chat_json)

    out = ca.call_agent(
        agent_name="test", system_prompt="sys", user_content="soru",
        schema=SimpleAnswer, tools=["get_current_time"], registry=reg, doc_id=None,
    )

    assert isinstance(out, SimpleAnswer)
    # With tools disabled, AgentStep is never requested — only the final schema.
    assert "AgentStep" not in seen_schemas
    assert seen_schemas == ["SimpleAnswer"]


def test_bad_args_are_fed_back_as_self_correction(monkeypatch):
    """An unknown tool name can't be emitted (Literal), but a tool raising is handled."""
    reg = ToolRegistry()

    def _boom():
        raise RuntimeError("kaboom")

    reg.register("flaky", _boom, _NoArgs, description_tr="patlar", timeout_s=2.0)
    seq = {"n": 0}

    def fake_chat_json(*, model, messages, schema, options=None):
        if schema.__name__ == "AgentStep":
            seq["n"] += 1
            if seq["n"] == 1:
                return '{"thought_tr":"deneyeyim","action":"flaky","args":{}}'
            # The error came back as a tool result; now finish.
            assert any("HATA" in m.get("content", "") for m in messages)
            return '{"thought_tr":"hata alındı, bitir","action":"finish","args":{}}'
        return '{"answer_tr":"tamam"}'

    monkeypatch.setattr(ca, "chat_json", fake_chat_json)
    out = ca.call_agent(
        agent_name="test", system_prompt="sys", user_content="dene",
        schema=SimpleAnswer, tools=["flaky"], registry=reg, doc_id=None,
    )
    assert isinstance(out, SimpleAnswer)
