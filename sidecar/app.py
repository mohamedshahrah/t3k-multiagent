"""FastAPI entry point. Single uvicorn worker (DuckDB is single-writer).

Endpoints:
  GET  /health                    liveness + model/db status
  POST /documents                 multipart upload -> intake -> kicks off the pipeline
  GET  /documents                 list + status
  GET  /documents/{id}            all artifacts joined (detail view)
  GET  /documents/{id}/trace      agent_log + tool_log (audit / reasoning trace)
  GET  /events                    SSE progress stream
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

import events
import states
from config import get_settings
from db import repositories as repo
from db.migrate import run_migrations
from intake import DuplicateDocument, process_upload
from ollama_client import list_models

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("evrak.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    applied = run_migrations()
    if applied:
        log.info("migrations applied: %s", applied)
    events.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="Evrak Asistanı Sidecar", version="0.1.0", lifespan=lifespan)

# The API is bound to 127.0.0.1 only. In the Wails window, requests go through the Go
# proxy (same-origin); CORS is here so the frontend can also be developed in a browser
# (vite dev on :5173) hitting the sidecar directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "model_tag": settings.model_tag,
        "tools_enabled": settings.tools_enabled,
        "models_present": list_models(),
    }


@app.post("/documents", status_code=202)
async def upload_document(file: UploadFile):
    content = await file.read()
    mime = file.content_type or "application/octet-stream"
    try:
        result = process_upload(filename=file.filename or "belge", content=content, mime=mime)
    except DuplicateDocument as e:
        return JSONResponse(
            status_code=409,
            content={"error": "duplicate", "existing_id": e.existing_id},
        )

    # Kick the reading pipeline off in a worker thread so SSE events flow while we return.
    from graph import run_document  # imported lazily so Phase-1 boot never needs a model
    asyncio.create_task(asyncio.to_thread(run_document, result["id"]))
    events.publish("document_ingested", result)
    return result


@app.get("/documents")
async def documents():
    return repo.list_documents()


@app.get("/documents/{doc_id}")
async def document_detail(doc_id: str):
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="belge bulunamadı")
    return {
        "document": doc,
        "pages": repo.get_pages(doc_id),
        "classification": repo.get_classification(doc_id),
        "summary": repo.get_summary(doc_id),
        "validation": repo.get_validation(doc_id),
    }


@app.get("/documents/{doc_id}/file")
async def document_file(doc_id: str):
    """Serve the original ingested file (inline) so the UI can preview it beside the text."""
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="belge bulunamadı")
    path = Path(doc["source_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="dosya diskte yok")
    return FileResponse(
        path, media_type=doc["mime"] or "application/octet-stream",
        filename=doc["filename"], content_disposition_type="inline",
    )


@app.get("/documents/{doc_id}/trace")
async def document_trace(doc_id: str):
    if repo.get_document(doc_id) is None:
        raise HTTPException(status_code=404, detail="belge bulunamadı")
    return repo.get_trace(doc_id)


@app.get("/events")
async def event_stream():
    return EventSourceResponse(events.subscribe())
