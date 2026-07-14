"""Tiny in-process pub/sub for SSE progress events.

The pipeline (which may run in a worker thread) publishes; the /events endpoint
subscribes. Publishing is thread-safe so agent/tool steps can emit from anywhere.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once at startup so background threads can hand events to the loop."""
    global _loop
    _loop = loop


def publish(event_type: str, data: dict[str, Any]) -> None:
    """Broadcast an event to all subscribers. Safe to call from any thread."""
    payload = {"type": event_type, **data}

    def _fanout() -> None:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _subscribers.discard(q)

    if _loop is not None and _loop.is_running():
        _loop.call_soon_threadsafe(_fanout)
    else:  # tests / startup before the loop is bound
        _fanout()


async def subscribe():
    """Async generator of SSE-shaped dicts for sse_starlette.EventSourceResponse."""
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.add(q)
    try:
        while True:
            payload = await q.get()
            yield {"event": payload["type"], "data": json.dumps(payload, ensure_ascii=False)}
    finally:
        _subscribers.discard(q)
