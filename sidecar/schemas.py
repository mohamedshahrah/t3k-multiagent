"""Pydantic contracts — the interfaces between agents and the rest of the pipeline.

The tool loop deliberately never changes these: the final object is identical whether
tools ran or not. `AgentStep` (the loop's per-step schema) is built dynamically per call
in call_agent because its `action` Literal depends on which tools were passed.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# --- Phase 1: dummy final contract used by the call_agent unit test ---------
class SimpleAnswer(BaseModel):
    answer_tr: str = Field(description="Kısa Türkçe cevap")


# --- Phase 2: Okuyucu (reading) --------------------------------------------
class PageTranscription(BaseModel):
    """One page transcribed to clean Turkish markdown."""
    text_tr: str = Field(description="Sayfanın temiz markdown metni")
    notes_tr: str = Field(default="", description="Okumada karşılaşılan sorunlar (varsa)")


class SignatureDetection(BaseModel):
    has_signature: bool = Field(description="Sayfada ıslak/elektronik imza var mı")
    has_stamp: bool = Field(description="Sayfada mühür/kaşe var mı")
    evidence_tr: str = Field(default="", description="Kısa gerekçe: nerede görüldü")
