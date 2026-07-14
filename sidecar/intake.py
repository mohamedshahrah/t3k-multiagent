"""Intake (no LLM): upload -> SHA-256 dedup -> UUIDv7 -> store -> documents row.

Digital-vs-scanned is detected here with PyMuPDF: a PDF whose total text-layer length
is below the threshold is treated as scanned (needs OCR in Phase 2). Images are scanned
by definition.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import fitz  # PyMuPDF

import states
from config import get_settings
from db import repositories as repo
from ids import new_uuid7

log = logging.getLogger("evrak.intake")

_EXT = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/tiff": ".tiff",
    "image/webp": ".webp",
}


class DuplicateDocument(Exception):
    def __init__(self, existing_id: str):
        self.existing_id = existing_id
        super().__init__(f"duplicate document, existing_id={existing_id}")


def _detect(path: Path, mime: str) -> tuple[int, bool]:
    """Return (page_count, is_scanned)."""
    if mime.startswith("image/"):
        return 1, True
    if mime == "application/pdf":
        threshold = get_settings().scanned_char_threshold
        with fitz.open(path) as doc:
            page_count = doc.page_count
            total_chars = sum(len(page.get_text("text")) for page in doc)
        return page_count, total_chars < threshold * max(page_count, 1)
    # Unknown/plain types: treat as single-page digital.
    return 1, False


def process_upload(*, filename: str, content: bytes, mime: str) -> dict:
    """Ingest one uploaded file. Raises DuplicateDocument if the SHA-256 already exists."""
    sha256 = hashlib.sha256(content).hexdigest()
    existing = repo.get_document_by_sha(sha256)
    if existing is not None:
        raise DuplicateDocument(str(existing["id"]))

    doc_id = new_uuid7()
    ext = _EXT.get(mime, Path(filename).suffix or ".bin")
    storage = Path(get_settings().storage_path)
    storage.mkdir(parents=True, exist_ok=True)
    dest = storage / f"{doc_id}{ext}"
    dest.write_bytes(content)

    page_count, is_scanned = _detect(dest, mime)
    repo.insert_document(
        doc_id=doc_id, sha256=sha256, filename=filename, mime=mime,
        source_path=str(dest), page_count=page_count, is_scanned=is_scanned,
        status=states.ALINDI,
    )
    log.info("ingested %s -> %s (pages=%d scanned=%s)", filename, doc_id, page_count, is_scanned)
    return {
        "id": str(doc_id), "filename": filename, "mime": mime,
        "page_count": page_count, "is_scanned": is_scanned, "status": states.ALINDI,
    }
