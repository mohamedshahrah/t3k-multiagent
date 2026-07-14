"""LangGraph pipeline. v0 (Phase 2): intake (done at upload) -> okuyucu.

Later phases add sınıflandırıcı, özetleyici, denetçi, triyaj, yönlendirici, yazıcı, cevap
and a SqliteSaver checkpointer + interrupt() for the human reply step. Kept deliberately
small here so a missing model never blocks Phase-1 boot.
"""
from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import events
from agents.okuyucu import read_document
from call_agent import reset_budget
from db import repositories as repo

log = logging.getLogger("evrak.graph")


class DocState(TypedDict):
    doc_id: str


def _okuyucu_node(state: DocState) -> DocState:
    doc = repo.get_document(state["doc_id"])
    if doc is not None:
        read_document(doc)
    return state


def _build_graph():
    builder = StateGraph(DocState)
    builder.add_node("okuyucu", _okuyucu_node)
    builder.add_edge(START, "okuyucu")
    builder.add_edge("okuyucu", END)
    return builder.compile()


_graph = _build_graph()


def run_document(doc_id: str) -> None:
    """Entry point invoked in a worker thread after intake. Never raises to the caller."""
    reset_budget(doc_id)
    try:
        _graph.invoke({"doc_id": doc_id})
    except Exception as exc:  # a missing model / bad scan must not crash the server
        log.exception("pipeline failed for %s", doc_id)
        events.publish("error", {"doc_id": doc_id, "message": str(exc)})
