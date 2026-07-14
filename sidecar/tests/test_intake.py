"""Intake: SHA-256 dedup, UUIDv7 id, and digital-vs-scanned detection (no LLM)."""
from __future__ import annotations

import fitz  # PyMuPDF
import pytest

import states
from intake import DuplicateDocument, process_upload


def _digital_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    body = (
        "T.C.\nÖRNEK ÜNİVERSİTESİ REKTÖRLÜĞÜ\n\n"
        "Sayı: 2026/42\nTarih: 12.07.2026\nKonu: Test belgesi hakkında\n\n"
        "İlgili makama,\n\n"
        "Bu yazı, evrak asistanı sisteminin sayısal (digital) metin katmanı içeren "
        "belgeleri doğru biçimde tanıyıp tanımadığını sınamak amacıyla hazırlanmıştır. "
        "Metin katmanı yeterli uzunlukta olduğundan belge taranmış değil, sayısal olarak "
        "sınıflandırılmalıdır. Gereğini bilgilerinize arz ederim.\n\n"
        "İmza\nBölüm Başkanı"
    )
    page.insert_text((72, 72), body)
    return doc.tobytes()


def _blank_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()  # no text layer -> should be detected as scanned
    return doc.tobytes()


def test_digital_pdf_ingests_and_is_not_scanned():
    result = process_upload(filename="yazi.pdf", content=_digital_pdf(), mime="application/pdf")
    assert result["status"] == states.ALINDI
    assert result["is_scanned"] is False
    assert result["page_count"] == 1
    assert len(result["id"]) == 36  # UUID string


def test_duplicate_is_rejected():
    content = _digital_pdf()
    first = process_upload(filename="a.pdf", content=content, mime="application/pdf")
    with pytest.raises(DuplicateDocument) as exc:
        process_upload(filename="a-again.pdf", content=content, mime="application/pdf")
    assert exc.value.existing_id == first["id"]


def test_blank_pdf_detected_as_scanned():
    result = process_upload(filename="tarali.pdf", content=_blank_pdf(), mime="application/pdf")
    assert result["is_scanned"] is True


def test_image_is_scanned():
    # 1x1 PNG
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00"
           b"\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6"
           b"\x178U\x00\x00\x00\x00IEND\xaeB`\x82")
    result = process_upload(filename="foto.png", content=png, mime="image/png")
    assert result["is_scanned"] is True
    assert result["page_count"] == 1
