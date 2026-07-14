"""Per-document context for the Okuyucu's tools.

Tools have fixed signatures (render_page(page_no, dpi, crop_box)) with no doc_id — the
"current document" is implicit. We carry it in a ContextVar that the registry copies into
the tool worker thread. Set it with `use_reading_doc(...)` around a call_agent invocation.
"""
from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

DPI_CEILING = 600
MAX_RENDERS_PER_PAGE = 3


@dataclass
class ReadingDoc:
    doc_id: str
    source_path: str
    _renders_per_page: dict[int, int] = field(default_factory=dict)

    def open(self) -> fitz.Document:
        return fitz.open(self.source_path)

    def can_render(self, page_no: int) -> bool:
        return self._renders_per_page.get(page_no, 0) < MAX_RENDERS_PER_PAGE

    def note_render(self, page_no: int) -> None:
        self._renders_per_page[page_no] = self._renders_per_page.get(page_no, 0) + 1


_current: contextvars.ContextVar[ReadingDoc | None] = contextvars.ContextVar(
    "reading_doc", default=None
)


def current() -> ReadingDoc:
    doc = _current.get()
    if doc is None:
        raise RuntimeError("no active reading document (use use_reading_doc)")
    return doc


@contextlib.contextmanager
def use_reading_doc(doc_id: str, source_path: str):
    token = _current.set(ReadingDoc(doc_id=doc_id, source_path=source_path))
    try:
        yield
    finally:
        _current.reset(token)
