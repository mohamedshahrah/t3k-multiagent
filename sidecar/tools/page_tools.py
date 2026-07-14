"""Okuyucu's tools: zoom/re-render a page region, or read a neighbouring page's text.

Importing this module self-registers the tools. Both are read-only. render_page returns
an ImageResult so the vision model re-reads the region; get_page_text returns plain text.
"""
from __future__ import annotations

import fitz  # PyMuPDF
from pydantic import BaseModel, Field

import reading_context as rc
from tools.registry import ImageResult, registry


class RenderPageArgs(BaseModel):
    page_no: int = Field(description="1'den başlayan sayfa numarası")
    dpi: int = Field(default=400, description="Çözünürlük (en çok 600)")
    crop_box: list[float] | None = Field(
        default=None,
        description="İsteğe bağlı kırpma [x0,y0,x1,y1], sayfa noktası koordinatlarında",
    )


class GetPageTextArgs(BaseModel):
    page_no: int = Field(description="1'den başlayan sayfa numarası")


def _render_page(page_no: int, dpi: int = 400, crop_box: list[float] | None = None) -> ImageResult:
    doc_ctx = rc.current()
    if not doc_ctx.can_render(page_no):
        return ImageResult(images=[], note_tr=f"Sayfa {page_no} için yeniden okuma sınırı doldu.")
    dpi = max(72, min(dpi, rc.DPI_CEILING))
    with doc_ctx.open() as pdf:
        idx = max(0, min(page_no - 1, pdf.page_count - 1))
        page = pdf[idx]
        clip = fitz.Rect(*crop_box) if crop_box else None
        pix = page.get_pixmap(dpi=dpi, clip=clip)
        png = pix.tobytes("png")
    doc_ctx.note_render(page_no)
    where = "kırpılmış bölge" if crop_box else "tam sayfa"
    return ImageResult(images=[png], note_tr=f"Sayfa {page_no}, {dpi} DPI, {where} yeniden işlendi.")


def _get_page_text(page_no: int) -> str:
    doc_ctx = rc.current()
    with doc_ctx.open() as pdf:
        idx = max(0, min(page_no - 1, pdf.page_count - 1))
        return pdf[idx].get_text("text") or "(bu sayfada metin katmanı yok)"


registry.register(
    "render_page", _render_page, RenderPageArgs,
    description_tr="Bir sayfayı daha yüksek çözünürlükte veya kırpılmış olarak yeniden işler "
                   "(okunması güç imza/mühür/bölgeler için).",
    timeout_s=20.0,
)
registry.register(
    "get_page_text", _get_page_text, GetPageTextArgs,
    description_tr="Komşu bir sayfanın metnini döndürür (başlık/altbilgi ve devam eden tablolar için).",
    timeout_s=5.0,
)
