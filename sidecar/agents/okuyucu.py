"""Okuyucu — turns any document into clean per-page Turkish text + signature/stamp flags.

Digital PDFs use the text layer (no LLM). Scanned pages/images use Gemma vision, and the
transcription call is AGENTIC: when a region is illegible it calls render_page to re-read
that region at higher DPI before finishing. Signature/stamp detection is a second vision
call per page that may zoom into a suspected signature block.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

import events
import reading_context as rc
import states
from call_agent import call_agent
from config import get_settings
from db import repositories as repo
from schemas import PageTranscription, SignatureDetection

# importing page_tools registers render_page / get_page_text
import tools.page_tools  # noqa: F401

log = logging.getLogger("evrak.okuyucu")

_TRANSCRIBE_SYS = (
    "Sen resmî belgeleri okuyan bir asistansın. Verilen sayfa görüntüsünü TEMİZ markdown "
    "metne çevir; başlıkları, listeleri ve tabloları koru. Bir bölge okunaksızsa, mühür ya "
    "da imza belirsizse render_page aracıyla o bölgeyi daha yüksek DPI'da/kırpılmış olarak "
    "yeniden iste ve öyle oku. Uydurma; okunmayanı [okunamadı] olarak işaretle."
)
_SIGNATURE_SYS = (
    "Sen belgede imza ve mühür tespiti yapan bir asistansın. Sayfada ıslak veya elektronik "
    "imza ve mühür/kaşe olup olmadığını belirle. Şüpheli bir imza/mühür bölgesi varsa "
    "render_page ile o bölgeyi bir kez yakınlaştırıp incele."
)


def _render_png(pdf_path: str, page_idx: int, dpi: int) -> bytes:
    with fitz.open(pdf_path) as pdf:
        page = pdf[max(0, min(page_idx, pdf.page_count - 1))]
        return page.get_pixmap(dpi=dpi).tobytes("png")


def _normalize(text: str) -> str:
    """Light OCR cleanup: de-hyphenate line breaks, fix common Turkish artifacts."""
    if not text:
        return text
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # hyphenated line breaks
    text = text.replace("ý", "ı").replace("þ", "ş").replace("ð", "ğ")  # legacy encoding slips
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_repeated_headers(pages_text: list[str]) -> list[str]:
    """Remove first/last lines that repeat across most pages (running header/footer)."""
    if len(pages_text) < 3:
        return pages_text
    firsts = Counter(p.strip().splitlines()[0] for p in pages_text if p.strip())
    lasts = Counter(p.strip().splitlines()[-1] for p in pages_text if p.strip())
    threshold = len(pages_text) // 2
    repeated = {ln for ln, c in (firsts | lasts).items() if c > threshold and len(ln) < 80}
    out = []
    for p in pages_text:
        lines = [ln for ln in p.splitlines() if ln.strip() not in repeated]
        out.append("\n".join(lines))
    return out


def _transcribe_scanned_page(doc_id: str, page_no: int, png: bytes) -> str:
    events.publish("tool_step", {"doc_id": doc_id, "agent": "okuyucu",
                                 "thought_tr": f"Sayfa {page_no} okunuyor…", "step_no": 0,
                                 "tool": "transcribe", "ok": True})
    result: PageTranscription = call_agent(
        agent_name="okuyucu",
        system_prompt=_TRANSCRIBE_SYS,
        user_content=f"Bu resmî belgenin {page_no}. sayfasını temiz markdown metne çevir.",
        images=[png],
        schema=PageTranscription,
        tools=["render_page", "get_page_text"],
        max_steps=3,
        doc_id=doc_id,
    )
    return result.text_tr


def _detect_signature(doc_id: str, page_no: int, png: bytes) -> SignatureDetection:
    return call_agent(
        agent_name="okuyucu-imza",
        system_prompt=_SIGNATURE_SYS,
        user_content=f"{page_no}. sayfada imza ve mühür var mı? render_page'i en çok 1 kez kullan.",
        images=[png],
        schema=SignatureDetection,
        tools=["render_page"],
        max_steps=2,
        doc_id=doc_id,
    )


def read_document(doc: dict) -> None:
    """Read one document end-to-end: fill pages + raw_text, set status OKUNDU."""
    doc_id = str(doc["id"])
    source_path = doc["source_path"]
    is_scanned = bool(doc["is_scanned"])
    page_count = int(doc["page_count"] or 1)
    settings = get_settings()

    events.publish("status", {"doc_id": doc_id, "status": "OKUNUYOR"})
    page_texts: list[str] = []

    with rc.use_reading_doc(doc_id, source_path):
        for page_no in range(1, page_count + 1):
            idx = page_no - 1
            image_path = None

            if is_scanned:
                png = _render_png(source_path, idx, dpi=200)
                pages_dir = Path(settings.storage_path) / "pages"
                pages_dir.mkdir(parents=True, exist_ok=True)
                image_path = str(pages_dir / f"{doc_id}_p{page_no}.png")
                Path(image_path).write_bytes(png)
                text = _transcribe_scanned_page(doc_id, page_no, png)
                sig_png = png
            else:
                with fitz.open(source_path) as pdf:
                    text = pdf[idx].get_text("text")
                sig_png = _render_png(source_path, idx, dpi=150)  # for the vision signature check

            sig = _detect_signature(doc_id, page_no, sig_png)
            text = _normalize(text)
            page_texts.append(text)
            repo.upsert_page(
                doc_id=doc_id, page_no=page_no, text=text, image_path=image_path,
                has_signature=sig.has_signature, has_stamp=sig.has_stamp,
            )

    page_texts = _strip_repeated_headers(page_texts)
    raw_text = "\n\n".join(f"--- Sayfa {i + 1} ---\n{t}" for i, t in enumerate(page_texts))
    repo.set_raw_text(doc_id, raw_text)
    repo.set_status(doc_id, states.OKUNDU)
    events.publish("status", {"doc_id": doc_id, "status": states.OKUNDU})
    log.info("okuyucu done: %s (%d pages, scanned=%s)", doc_id, page_count, is_scanned)
