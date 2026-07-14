# Evrak Asistanı — Project Work Plan (6 Phases, Docker-based, tool-using agents)

Pure build plan: what to build, in what order, split across 4 people. No dates — phases are ordered by dependency; a phase starts when its prerequisites are done. Work top to bottom.

**Project:** local, end-to-end multi-agent AI system for public document & correspondence processing (Turkish). User drops a PDF/image → agents read (OCR), classify, extract fields, summarize, validate against rules (missing info + signature check, with rule citations), route to the right department/person, draft the official letter; recipient answers via short chat message → agent produces the formal official reply.

**Architecture stance (read this first):** the backbone is a **deterministic workflow** (fixed LangGraph DAG, schema-constrained agent outputs). On top of it, five specific nodes are **tool-using agents** — they decide what evidence to fetch, fetch it, and iterate before committing to their schema-constrained answer. Agentic behavior is *bounded* (max steps, tool budget, hard fallback to single-shot) and *earned* (a node stays agentic only if the eval harness shows it beats the single-shot path). We do not agentify the happy path for the sake of the word.

---

## ✅ Progress (as of 2026-07-13)

Phases **0–2 are built and verified on one machine** (RTX 4060, 8 GB VRAM). Legend: ✅ done · 🟡 partial · ⬜ not started.

| Phase | Status | Notes |
|---|---|---|
| 0 · Fixed decisions | ✅ | Realized as the repo skeleton + committed `uv.lock` + 3 compose files. **Model tags corrected `gemma4 → gemma3`** — `gemma4` does not exist on Ollama; system runs `gemma3:12b` (main) / `gemma3:4b` (fallback), env-driven. |
| 1 · Foundations | ✅ | `docker compose up` runs ollama (GPU) + sidecar; intake + SHA-256 dedup + UUIDv7; `call_agent` bounded tool loop (7 unit tests pass **in-container**); FastAPI endpoints; DuckDB schema v1 + migrations; seeds (6 birim, 12 kullanıcı); Svelte shell; **Wails desktop app runs**. Verified on **1 machine, not 4**. |
| 2 · Reading | 🟡 | Okuyucu OCR + agentic zoom loop **verified against `gemma3:4b`** (real Turkish transcription + self-correcting `render_page`); signature/stamp; normalization; LangGraph `intake→okuyucu`; SSE tool-step events; Evrak Detayı v0 **with original-document preview**. |
| 3 · Understanding | ⬜ | Not started. |
| 4 · Acting | ⬜ | Not started. |
| 5 · Product experience | ⬜ | Not started. |
| 6 · Quality/release | ⬜ | Not started. |

**⛔ NOT DONE (explicit gaps):**
- **Phase 2 · R2:** the 10-doc reading **test set** and the **tools-on vs tools-off A/B** (readability + latency) were NOT built — the capability exists and was verified on one document, but the acceptance dataset/metrics run has not happened.
- Verified on **`gemma3:4b` only** (8 GB GPU). `gemma3:12b` was **not** test-run (won't fit VRAM for image OCR on this machine).
- **GUI click-through is manual/visual** (not automated); the "identical on all four machines" check was not performed (single machine).
- Everything in **Phases 3–6**.

> Below, in the phase task lists, `- [x]` = done in this build, `- [ ]` = still to do.

---

## 0. Fixed Technical Decisions (do not re-debate mid-project)

| Area | Decision |
|---|---|
| **Runtime environment** | **Docker Compose runs the whole backend** — `ollama` container (GPU) + `sidecar` container (FastAPI/LangGraph/DuckDB). One `docker compose up` gives every member the identical environment; debugging via container logs + debugpy. Only the Wails desktop window runs natively (a native WebView cannot live in a container) — it is a thin shell that just talks to `localhost` |
| LLM (all agents) | `gemma4:12b` via **Ollama** — multimodal (vision/OCR), 256K context, Apache 2.0, ~7.6 GB Q4 → fits 8–12 GB NVIDIA. Fallback for weak machines: `gemma4:e4b` (env-var switch, never hardcode the model tag) |
| Embeddings | `bge-m3` via Ollama — 1024 dimensions, MIT license, strong Turkish |
| Optional drafting specialist | `ytu-ce-cosmos/Turkish-Gemma-9b-T1` (GGUF → Ollama Modelfile) — adopt **only** if the Phase 4 blind A/B shows it clearly beats Gemma 4 at formal Turkish |
| Database | **DuckDB**, single file at `/data/db/evrak.duckdb` **inside the sidecar container** (embedded DB — it is a library, not a server, so it needs no container of its own). `./data` is bind-mounted so the file is inspectable from the host. Embeddings inline as `FLOAT[1024]`; similarity via `array_cosine_similarity`; Turkish full-text via the FTS extension. No separate vector DB |
| Orchestration | Python 3.12 sidecar image: **FastAPI + LangGraph** (SqliteSaver checkpoints; `interrupt()` for the human reply step). Dependencies locked with `uv` (`uv.lock` committed) — the image build is reproducible byte-for-byte |
| Desktop app | **Wails v2** (Go) + **Svelte** frontend, running on the host. Wails v3 is alpha — not allowed |
| **Agent I/O** | Every agent call = system prompt (Turkish) + **JSON-schema-constrained output** validated by a Pydantic model. No free-text outputs between agents — **this holds for tool-using agents too** (see below) |
| **Tool use (agentic layer)** | **No native/OpenAI-style function calling.** Gemma's tool-calling is unreliable and a second tool-capable model would cost a VRAM swap. Instead the tool loop reuses the schema-constrained mechanism we already have: the agent emits an `AgentStep` object (`{thought_tr, action, args}`), the sidecar executes the tool, appends the result, and calls again. When the agent emits `action="finish"`, one **final** schema-constrained call produces the real Pydantic contract object. Same wrapper, same contracts, zero new dependencies, model-agnostic |
| **Agentic scope** | Tool loops exist in exactly 5 nodes: **Okuyucu** (zoom/re-render), **Denetçi** (iterative rule retrieval), **Yönlendirici** (department/precedent search), **Yazıcı** (format self-critique), **Triyaj** (ambiguity resolution). Everything else stays single-shot. Adding a 6th requires eval evidence |
| **Agentic guardrails** | Every loop has `max_steps` (default 5), a per-document tool-call budget, a per-tool timeout, and a **hard fallback** to the existing single-shot path if the loop does not converge. `TOOLS_ENABLED` env flag turns the whole layer off for A/B eval and as a demo-day panic switch |
| Identity | Every file: **UUIDv7** primary key + **SHA-256** hash (UNIQUE) for duplicate rejection. Every downstream artifact references the UUID |
| Language | User-facing text: Turkish. Code, comments, commit messages: English |

### The tool loop (the one pattern everything agentic uses)

```
call_agent(agent, system_prompt, user_content, images, schema, tools=[...], max_steps=5)

  ┌─ step 1..max_steps ──────────────────────────────────────────┐
  │  LLM → AgentStep {thought_tr, action, args}   (schema-forced) │
  │     action == "finish"  → break                               │
  │     else → registry[action](**args) → append result to msgs   │
  └──────────────────────────────────────────────────────────────┘
  final call → LLM → schema (ValidationReport / RoutingDecision / …)
  every step written to tool_log; the whole loop written to agent_log
```

- `tools=[]` (the default) ⇒ behaves exactly like today's single-shot call. Nothing regresses.
- If `max_steps` is exhausted without `finish`: log it, fall back to the single-shot prompt with whatever was retrieved, mark `agent_log.degraded = true`.
- **Nothing bypasses `call_agent`.** Tools are registered, not ad-hoc.

### Container topology

```
┌─ HOST (Windows) ─────────────────────────────────────────────────────────┐
│  Wails v2 desktop app (Go shell + Svelte UI)                             │
│  · talks to http://127.0.0.1:8756 (sidecar)                              │
│  · can run `docker compose up -d` itself if the stack is down            │
│                                                                          │
│  ┌─ Docker Compose (WSL2 backend) ───────────────────────────────────┐   │
│  │                                                                   │   │
│  │  sidecar  (build: ./sidecar)            ollama (ollama/ollama)    │   │
│  │  FastAPI + LangGraph + DuckDB           gemma4:12b · bge-m3       │   │
│  │  + tool registry (rules/pages/dept/     port: 127.0.0.1:11434     │   │
│  │    format/precedent tools)              GPU: --gpus=all (NVIDIA)  │   │
│  │  ports: 127.0.0.1:8756 (API)            volume: ollama-models     │   │
│  │         127.0.0.1:5678 (debugpy)        (models pulled once,      │   │
│  │  mounts: ./sidecar → /app (hot reload)   survive rebuilds)        │   │
│  │          ./data    → /data (db+files)                             │   │
│  │  env: OLLAMA_URL=http://ollama:11434                              │   │
│  │       DB_PATH=/data/db/evrak.duckdb                               │   │
│  │       MODEL_TAG=gemma4:12b · TOOLS_ENABLED=1 · MAX_TOOL_STEPS=5   │   │
│  └───────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

**Compose layout (created in Phase 1):**
- `docker-compose.yml` — base: both services, GPU reservation for ollama, named volume `ollama-models`, restart policy `unless-stopped`, healthchecks
- `docker-compose.override.yml` — dev (picked up automatically): bind-mounts source into `/app`, `uvicorn --reload`, debugpy on 5678
- `docker-compose.demo.yml` — demo profile: no source mounts, baked image, no debug port
- `sidecar/Dockerfile` — `python:3.12-slim` → install `uv` → `uv sync --frozen` → non-root user → `CMD uvicorn app:app --host 0.0.0.0 --port 8756`
- `.dockerignore`, and all ports published on `127.0.0.1` only (nothing exposed to the network)

**Team rules that make "same env" true:**
- Python is **never** run on the host. Every script, eval run, and migration executes inside the container: `docker compose exec sidecar uv run …`
- `uv.lock` and base-image tags are pinned; changing either requires a PR.
- Model pulls go into the `ollama-models` named volume via `scripts/pull-models.ps1` (`docker compose exec ollama ollama pull gemma4:12b` etc.) — pulled once per machine, survive `compose down`.
- Debugging: `docker compose logs -f sidecar` for logs; VS Code "attach to debugpy :5678" config committed in `.vscode/launch.json`; DuckDB file openable from the host (`./data/db/evrak.duckdb`) with the DuckDB CLI while the app is stopped.
- **Allowed exception (document it in README):** a member whose machine cannot do GPU-in-Docker may run Ollama natively on the host and set `OLLAMA_URL=http://host.docker.internal:11434` for the sidecar. The sidecar (all our code) stays containerized — only the stateless model server differs.

### Repo layout

```
evrak-asistani/
  docker-compose.yml
  docker-compose.override.yml   # dev: hot reload + debugpy
  docker-compose.demo.yml       # demo: baked image, no mounts
  main.go, app.go               # Wails shell: window, drag&drop, stack health/start, HTTP proxy, event relay
  frontend/                     # Svelte UI (Turkish labels)
  sidecar/
    Dockerfile
    app.py                      # FastAPI entry (single uvicorn worker — DuckDB single-writer)
    graph.py                    # LangGraph pipeline definition
    call_agent.py               # THE wrapper: schema-forced call + bounded tool loop + logging
    agents/                     #   okuyucu.py, siniflandirici.py, ozetleyici.py, denetci.py,
                                #   yonlendirici.py, yazici.py, cevap.py, triyaj.py
    tools/                      # ← NEW: one module per tool + registry.py
      registry.py               #   name → {fn, args_schema, description_tr, timeout}
      rules_tools.py            #   search_rules, get_madde, get_requirements
      page_tools.py             #   render_page (dpi/crop), get_page_text
      routing_tools.py          #   search_departments, list_users, find_similar_past_docs
      format_tools.py           #   check_letter_format
      human_tools.py            #   ask_user  (bridges to LangGraph interrupt())
    rag/                        # chunker.py, embedder.py, retriever.py (dense + FTS + RRF)
    db/                         # connection.py, migrations/, repositories.py
    eval/                       # run_eval.py, metrics.py, report.py  (runs with TOOLS_ENABLED 0 and 1)
    pyproject.toml, uv.lock     # locked deps = reproducible image
  data/                         # BIND-MOUNTED into the container at /data
    db/                         #   evrak.duckdb + langgraph checkpoints
    storage/                    #   ingested original files + rendered page images
    rules/                      #   correspondence regulation + fictional university directives
    synthetic/                  #   generated test documents + ground-truth labels
    seeds/                      #   demo users, departments
  docs/                         # Turkish README, architecture, license inventory, metrics
  scripts/                      # setup.ps1, pull-models.ps1, dev.ps1, demo.ps1, generate_data.py
  .vscode/launch.json           # attach-to-debugpy config (shared)
```

### Team roles (assign once, own but cross-review)

| Code | Role | Owns |
|---|---|---|
| **R1** | AI & Agents | LangGraph pipeline, `call_agent` + tool loop, **tool registry**, all agent prompts + schemas, Ollama integration |
| **R2** | Data, RAG & Eval | Rules corpus, synthetic dataset + labels, retrieval, eval harness & metrics, **tools-on vs tools-off A/B** |
| **R3** | Frontend | All Svelte screens, streaming UX, **agent reasoning-trace UI**, Turkish UI text |
| **R4** | Platform | Docker/compose, Go/Wails shell, DuckDB schema & migrations, packaging, scripts |

---

## Phase 1 — Foundations: identical environment + everything talks to everything

**Goal:** `docker compose up` gives every member the same running backend; empty but fully wired skeleton — UI ↔ Go ↔ sidecar container ↔ ollama container ↔ DuckDB round trip works identically on all four machines. **The tool loop exists from day one, with zero tools registered.**
**Prerequisites:** none.

### Tasks

**Environment (everyone)**
- [x] Install Docker Desktop (WSL2 backend enabled) + current NVIDIA driver; verify GPU passthrough — **done**, ollama container sees the RTX 4060
- [x] Install Go ≥1.22, Node LTS, Wails v2 CLI — **done** (Go 1.26, Node 24, Wails v2.13.0)
- [x] Clone repo → `scripts/setup.ps1` → `docker compose up -d` → `scripts/pull-models.ps1` — **done** (scripts written; stack up; pulled `gemma3:4b` — note `gemma4` tag corrected to `gemma3`; `gemma3:12b` NOT pulled, won't fit 8 GB)
- [x] Sanity test via container: one Turkish text prompt + one image prompt — **done** (image OCR exercised end-to-end; `scripts/smoke-test.ps1` written)

**Docker & compose (R4) — build this first, everything else runs inside it**
- [x] `sidecar/Dockerfile`: `python:3.12-slim`, `uv sync --frozen`, non-root user, healthcheck, CMD uvicorn — **done** (dev group included so tests/eval run in-container)
- [x] `docker-compose.yml`: ollama (GPU reservation, volume, healthcheck) + sidecar (build, `./data:/data`, env incl. `TOOLS_ENABLED/MAX_TOOL_STEPS/TOOL_BUDGET_PER_DOC`, `depends_on` healthy, `127.0.0.1` only) — **done** (`MODEL_TAG` default `gemma3:12b`)
- [x] `docker-compose.override.yml` (dev): source mount, `--reload`, debugpy 5678; `.vscode/launch.json` — **done** (fixed a YAML fold bug in the command)
- [x] `docker-compose.demo.yml`: baked image, no mounts, no debug port — **done**
- [x] `scripts/`: `dev.ps1`, `pull-models.ps1`, `smoke-test.ps1`, `logs.ps1` — **done** (+ `setup.ps1`, `demo.ps1`)

**App shell (R4)**
- [x] Wails + Svelte; **window opens** — done (compiled binary runs, PID confirmed against the live stack)
- [x] Stack manager in Go: health-check, `docker compose up -d` if down, "Servis başlatılıyor…" splash, **error screen with retry button** — done
- [x] Wails bindings: `Api(method, path, body)` proxy, `OpenFileDialog()`, SSE→`EventsEmit` relay — done (+ native `OnFileDrop` drag&drop, `UploadFile`, `StackStatus`/`StartStack`)

**Database (R4)**
- [x] Migration runner inside the sidecar (numbered .sql, `schema_migrations`) — done; DB at `/data/db/evrak.duckdb`
- [x] Schema v1 — done (`db/migrations/001_init.sql`, all tables incl. `agent_log`/`tool_log`):

```sql
documents(id UUID PRIMARY KEY, sha256 TEXT UNIQUE, filename TEXT, mime TEXT,
          source_path TEXT, page_count INT, is_scanned BOOL,
          status TEXT, received_at TIMESTAMP, raw_text TEXT)
pages(doc_id UUID, page_no INT, text TEXT, image_path TEXT,
      has_signature BOOL, has_stamp BOOL)
classifications(doc_id UUID, doc_type TEXT, confidence FLOAT, entities JSON)
summaries(doc_id UUID, summary_tr TEXT, one_liner TEXT, model TEXT, latency_ms INT)
validations(doc_id UUID, is_compliant BOOL, missing_fields JSON,
            matched_rules JSON, report_tr TEXT)
routings(doc_id UUID, department_id INT, user_id INT, rationale_tr TEXT, confidence FLOAT)
drafts(id UUID, doc_id UUID, draft_type TEXT, content_tr TEXT, version INT, status TEXT)
users(id INT, name TEXT, email TEXT, title TEXT, department_id INT)
departments(id INT, name TEXT, responsibilities_tr TEXT, embedding FLOAT[1024])
rules_chunks(id INT, source TEXT, madde_no TEXT, doc_types JSON,
             text_tr TEXT, embedding FLOAT[1024])
doc_type_requirements(doc_type TEXT, required_elements JSON)
deliveries(id UUID, doc_id UUID, draft_id UUID, to_user_id INT, status TEXT, delivered_at TIMESTAMP)
chat_messages(id UUID, doc_id UUID, user_id INT, role TEXT, content TEXT, ts TIMESTAMP)

-- agent_log gains the agentic columns
agent_log(id UUID, doc_id UUID, agent TEXT, model TEXT,
          input_summary TEXT, output_summary TEXT,
          tool_steps INT,          -- how many loop iterations
          degraded BOOL,           -- loop failed → single-shot fallback used
          latency_ms INT, ts TIMESTAMP)

-- NEW: one row per tool invocation = the reasoning trace
tool_log(id UUID, doc_id UUID, agent_log_id UUID, step_no INT,
         tool TEXT, thought_tr TEXT, args JSON,
         result_summary TEXT, ok BOOL, latency_ms INT, ts TIMESTAMP)
```

**Sidecar skeleton (R1)**
- [x] FastAPI app with endpoints — done (+ `GET /documents/{id}/file` for the preview; CORS for browser-dev): `GET /health` · `POST /documents` (multipart upload) · `GET /documents` (list + status) · `GET /documents/{id}` (all artifacts joined) · **`GET /documents/{id}/trace` (agent_log + tool_log, for the audit screen)** · `GET /events` (SSE progress stream)
- [x] `uv` project, pinned deps, `uv.lock` committed, `MODEL_TAG` env — done (`uuid-utils` added for UUIDv7) (`fastapi uvicorn langgraph langgraph-checkpoint-sqlite ollama duckdb pymupdf pydantic sse-starlette debugpy`); `uv.lock` committed; model tag read from `MODEL_TAG` env var
- [x] **`call_agent`** — done, with the bounded tool loop (unit-tested in-container: tool call, self-correction on bad args, `finish`, single-shot fallback when `TOOLS_ENABLED=0`):
  `call_agent(agent_name, system_prompt, user_content, images=None, schema=PydanticModel, tools=None, max_steps=MAX_TOOL_STEPS)`
  - `tools=None` → today's behavior exactly: one schema-forced call, retry ≤2× on invalid JSON with the validation error appended, log, return typed object
  - `tools=[...]` and `TOOLS_ENABLED=1` → loop: force the `AgentStep` schema (`{thought_tr, action, args}`), dispatch `action` through the tool registry, append the tool result as a new message, repeat until `action="finish"` or `max_steps`; then one final schema-forced call returning the real Pydantic object
  - Every iteration → a `tool_log` row. Every call → an `agent_log` row (`tool_steps`, `degraded`, latency)
  - Unknown action / bad args / tool timeout → feed the error back to the model as the tool result (self-correction), count it as a step
  - Loop exhausted → `degraded=true`, fall back to the single-shot prompt with whatever the tools already returned
- [x] **Tool registry** (`tools/registry.py`) — done, dummy `get_current_time` proven in the unit test: `register(name, fn, args_schema: BaseModel, description_tr, timeout_s)`. Tool descriptions in Turkish are rendered into the system prompt. **Empty in Phase 1** — the machinery is proven with one dummy tool (`get_current_time`) in a unit test, real tools arrive per phase
- [x] **İntake** (no LLM) — done, verified via curl (upload→202+UUIDv7, re-upload→409): upload → SHA-256 → if hash exists return `409 {"error":"duplicate","existing_id":...}` → else UUIDv7, copy file to `/data/storage/`, insert `documents` row with `status='ALINDI'`, detect digital-vs-scanned (PyMuPDF total text-layer chars < threshold → scanned)

**Seeds & UI shell (R2, R3)**
- [x] **(R2)** — done (`db/seed.py`, `data/seeds/*.json`): ~6 fictional departments with 2–3 sentence responsibility descriptions (Öğrenci İşleri, Personel Daire Başkanlığı, Hukuk Müşavirliği, Strateji Geliştirme, Bilgi İşlem, Rektörlük Özel Kalem) + ~12 fictional users (name, title, email, department); seed script runs via `docker compose exec sidecar uv run python -m db.seed`
- [x] **(R3)** Svelte shell — done: sidebar (Gelen Evrak · Evrak Detayı · Gelen Kutusu · Yönetim · Denetim Kaydı), drop-zone (drag&drop + picker), document list with status chips, duplicate toast, live SSE feed

### Done when
- On all four machines: fresh clone → `setup.ps1` → `docker compose up -d` → `pull-models.ps1` → app opens → drop a PDF → `documents` row with UUID appears in the UI; re-drop → duplicate message; `docker compose logs -f sidecar` shows the request; VS Code attaches to debugpy and hits a breakpoint in the upload handler. **The `call_agent` tool loop passes its unit test with the dummy tool (model calls it, gets the result, finishes, returns a valid Pydantic object) and with `TOOLS_ENABLED=0` falls back to single-shot.** Identical behavior everywhere = the phase's whole point.

---

## Phase 2 — Reading: every document becomes clean text

**Goal:** Any input (digital PDF, scanned PDF, photo/image) comes out as clean per-page text with signature/stamp flags. **First real agentic node: the Okuyucu can zoom.**
**Prerequisites:** Phase 1.

### Tasks
- [x] **(R1)** Digital path: PyMuPDF text-layer extraction per page → `pages.text`, concatenated → `documents.raw_text` — done
- [x] **(R1)** Scanned path: render 200 DPI PNG under `/data/storage/pages/` → Gemma **3** vision transcription to markdown — done (verified: real Turkish text from an image-only PDF)
- [x] **(R1) TOOLS — `page_tools.py`:** — done
  - `render_page(page_no: int, dpi: int = 400, crop_box: [x0,y0,x1,y1] | None)` → renders (and caches) a higher-resolution or cropped image of the page, returns it as a new image message
  - `get_page_text(page_no: int)` → text of a neighbouring page (header/footer disambiguation, continued tables)
- [x] **(R1) Okuyucu as an agent (self-correcting OCR):** — done & verified (model called `render_page` with a wrong-shaped `crop_box`, got the schema error back, and self-corrected to the list form — captured in `tool_log`). `tools=[render_page, get_page_text]`, `max_steps=3`. It reads at 200 DPI; when a region is illegible, a stamp is unreadable, or a signature block is ambiguous, it calls `render_page(page_no, dpi=400, crop_box=…)` and re-reads that region before finishing. **This replaces the old "if persistent, add a retry-at-higher-DPI path" risk mitigation with a real mechanism.** Hard caps: ≤3 renders per page, 600 DPI ceiling, per-render timeout
- [x] **(R1)** Signature/stamp detection — done: second vision call per page → schema `{has_signature: bool, has_stamp: bool, evidence: str}`; **may call `render_page` with a crop around the suspected signature area (max 1 extra step)**; aggregate to document level (any page signed → document signed)
- [x] **(R1)** Normalization pass — done: de-hyphenation, Turkish char fixes, running header/footer removal
- [x] **(R1)** LangGraph v0: `intake → okuyucu`; `ALINDI → OKUNDU`; SSE progress incl. tool-step events — done
- [ ] ⛔ **NOT DONE — (R2)** Reading test set: 10 documents (4 digital, 4 scanned incl. a bad scan, 2 photos; 5 signed). Manual accuracy check; **run twice `TOOLS_ENABLED=0/1` and record readability + latency (the first A/B data point).** ← this acceptance dataset was not built; capability verified on 1 doc only
- [x] **(R3)** Evrak Detayı v0 — done: original preview (iframe/img via `/documents/{id}/file`) beside extracted text; signature/stamp badges; scanned/digital indicator; "🔍 N kez yeniden okundu" zoom chip

### Done when
- All 10 test docs produce readable Turkish text and correct signature flags; a scanned and a digital doc both reach status `OKUNDU` automatically after drop — verified on at least two members' machines with identical results. **The deliberately bad scan is measurably better with tools on than off (or we record that it isn't, and say so).**

---

## Phase 3 — Understanding (competition Task 1): classify, extract, summarize, validate

**Goal:** After reading, the system automatically produces: document type + extracted fields + summary + rule-based validation report with missing-info list and rule citations. **The Denetçi becomes an agentic-RAG agent — it searches the rulebook iteratively instead of judging one pre-fetched top-k.**
**Prerequisites:** Phase 2.

### Tasks

**Rules infrastructure (R2) — build first, validator depends on it**
- [ ] Rules corpus: official correspondence regulation (public text) + 8–10 fictional university directives (yönerge) written in proper formal Turkish → `data/rules/`
- [ ] Chunker: split by article (madde), metadata `{source, madde_no, doc_types[]}` → `rules_chunks`
- [ ] Embedder: `bge-m3` for every chunk (and for the 6 department descriptions) → `FLOAT[1024]` columns; run as `docker compose exec sidecar uv run python -m rag.embed_rules`
- [ ] Retriever: dense top-k via `array_cosine_similarity` + DuckDB FTS index (turkish stemmer) BM25 top-k → merge with reciprocal rank fusion → single `retrieve(query, doc_type, k)` function
- [ ] `doc_type_requirements` content: per document type, the JSON list of mandatory elements (dilekçe: ad, tarih, imza, talep; fatura: tutar, vergi no, tarih; resmî yazı: sayı, tarih, konu, imza; …)

**Tools (R1 + R2) — `rules_tools.py`**
- [ ] `search_rules(query: str, doc_type: str | None, k: int = 5)` → wraps `retrieve()`; returns `[{chunk_id, source, madde_no, text_tr (truncated), score}]`. **The agent writes the query, not the code**
- [ ] `get_madde(source: str, madde_no: str)` → full untruncated article text — used to quote a rule correctly before citing it
- [ ] `get_requirements(doc_type: str)` → the `doc_type_requirements` row, so the agent can check the checklist itself instead of being handed it
- [ ] All three are read-only, sub-100 ms, and safe to call repeatedly. Results are deduplicated per document so the agent cannot burn its budget re-fetching the same chunk

**Agents (R1)**
- [ ] **Sınıflandırıcı** *(single-shot, no tools — a fixed prompt is enough and it's on the hot path)*: input raw_text (first N chars) → output `{doc_type, confidence, entities:{gönderen, gönderen_kurum, tarih, sayı, konu, talep, ekler[], son_tarih}}`. Taxonomy v1 (8 types): dilekçe, resmî yazı, davet, rapor, fatura, itiraz, izin talebi, staj başvurusu. 2–3 few-shot examples per ambiguous pair in the prompt
- [ ] **Özetleyici** *(single-shot, no tools)*: 3–5 sentence formal Turkish summary + one-line konu → `summaries`
- [ ] **Denetçi — agentic RAG**, two layers merged into one report:
  - (a) **deterministic** — check every `doc_type_requirements` element against extracted entities + signature flag (code, not LLM). Unchanged, runs first, its output is fed to the agent as a starting hypothesis
  - (b) **agentic semantic** — `tools=[search_rules, get_madde, get_requirements]`, `max_steps=5`. Typical trace: search for the document type's general rules → notice the signature is missing → **search again, specifically for signature/imza rules** → `get_madde` to read the exact article → finish. Final schema: `{is_compliant, missing_fields[], matched_rules:[{source, madde_no, quote_tr}], report_tr}`
  - Every finding **must** cite a madde number that appears in the tool results. **Post-validation in code:** any `matched_rules` entry the agent never actually retrieved is a hallucinated citation → drop it and log it as a metric (`citation_groundedness`). This is a hard anti-hallucination gate that only exists *because* we have the tool trace
- [ ] LangGraph Task-1 wiring: `okuyucu → sınıflandırıcı → (özetleyici ∥ denetçi) → join`; parallel fan-out/fan-in; conditional edge: `confidence < 0.6` → **`triyaj`** (see below) instead of a dead-end human queue
- [ ] **Triyaj agent (new, replaces the `İNCELEME_GEREKLİ` dead end):** `tools=[get_page_text, render_page, search_rules, find_similar_past_docs]`, `max_steps=4`, **read-only, cannot change status by itself**. It tries to resolve the ambiguity (re-read a specific page, look for a decisive rule, find a similar past document). Output: `{resolved: bool, proposed_doc_type, confidence, findings_tr, evidence[]}`. If `resolved` and confidence ≥ 0.6 → the pipeline continues. Otherwise → status `İNCELEME_GEREKLİ`, but the human now opens the document and sees **the agent's findings and what it already checked**, not an empty queue item

**Data & measurement (R2)**
- [ ] Synthetic dataset v1: generator script → **60 labeled documents** across the 8 types (LLM-drafted, human-reviewed), ~15 rendered to PNG as fake scans, several with planted defects (missing signature/sayı/tarih, inconsistent attachment count); label JSON per doc: `{doc_type, entities, correct_department, planted_missing_fields[], expected_maddeler[]}` ← **new label: which articles *should* be cited**
- [ ] **Eval harness v0 — every run is a matrix:** `docker compose exec sidecar uv run python -m eval.run_eval --tools=0` and `--tools=1` → classification accuracy, entity extraction F1, missing-info detection precision/recall, **citation groundedness (% of cited maddeler actually retrieved), citation correctness (vs `expected_maddeler`), mean tool steps per doc, degraded-loop rate**, per-stage latency → markdown report with **both columns side by side**. Because it runs in the container, numbers are comparable across members' machines (same env, only GPU speed differs)
- [ ] First baseline run recorded in `docs/metrics-baseline.md`; targets to iterate toward: classification ≥85 %, missing-info recall ≥80 %, citation groundedness ≥95 % (adjust after seeing the baseline)
- [ ] **Decision rule, written down:** the Denetçi stays agentic only if tools-on beats tools-off on missing-info recall **or** citation correctness by a margin worth the latency. If it doesn't, we ship single-shot and *report that finding* — a negative result honestly measured is worth more than a buzzword

**UI (R3)**
- [ ] Evrak Detayı v1: type + confidence badge · entities table · summary card · validation report with red missing-field warnings and cited rules (madde chips, **clicking a chip shows the quoted article text the agent actually retrieved**) · `İNCELEME_GEREKLİ` state styling **showing the Triyaj agent's findings**

### Done when
- Eval harness runs over all 60 docs unattended inside the container in **both** tool modes, no crashes, every doc has rows in `classifications`, `summaries`, `validations`, and a populated `tool_log`; baseline metrics for both modes are written down; dropping any synthetic doc shows all Task-1 artifacts in the UI without touching a terminal; **no hallucinated madde citation survives to the UI**.

---

## Phase 4 — Acting (competition Task 2): route, draft, deliver, reply

**Goal:** Validated documents automatically get a routing decision and an official draft letter; the recipient replies via short chat and the system produces + sends the formal reply. **Router and drafter become tool-using agents; the drafter critiques its own output before showing it to anyone.**
**Prerequisites:** Phase 3 (classifier/validator outputs stable).

### Tasks

**Tools (R1) — `routing_tools.py`, `format_tools.py`, `human_tools.py`**
- [ ] `search_departments(query: str, k: int = 3)` → cosine over `departments.embedding`; the **agent** writes the query, so it can re-search with different phrasing when the first result set is ambiguous
- [ ] `list_users(department_id: int)` → name, title, email, current open-document count (workload)
- [ ] `find_similar_past_docs(query: str, k: int = 3)` → RRF over past `documents` + their `routings`: *"who handled a document like this last time?"* Returns `[{doc_id, one_liner, department, user, was_overridden}]`. **Routing precedent is the single strongest signal we own and today's plan doesn't use it at all**
- [ ] `check_letter_format(content_tr: str, draft_type: str)` → **pure code, no LLM**: verifies every mandatory element (başlık, sayı, tarih, konu, ilgi, gövde, imza bloğu, ek listesi) and returns `{ok: bool, missing: [...], warnings: [...]}`. **This is the same checker R2 needs for the Phase 4 quality gate — write it once, use it as both a runtime tool and an eval metric**
- [ ] `ask_user(question_tr: str)` → bridges to LangGraph `interrupt()`; the graph sleeps, the question appears as a chat bubble, the answer comes back as the tool result. Max 2 uses per document (enforced in the registry, not by the prompt)

**Agents (R1)**
- [ ] **Yönlendirici — tool-using router:** `tools=[search_departments, list_users, find_similar_past_docs]`, `max_steps=4`. Instead of code pre-fetching top-3 departments and stuffing them in the prompt, the agent searches, checks precedent, looks at who is actually free, and decides: `{department_id, user_id, rationale_tr, evidence[], confidence}`. `rationale_tr` must reference something it retrieved (precedent doc or department description) — grounded, not vibes. `confidence < 0.6` → dispatcher queue (with its evidence attached)
- [ ] **Yazıcı — draft + self-critique loop:** `tools=[check_letter_format, get_madde, get_document_context]`, `max_steps=4`. Chooses draft type from classification+routing context (üst yazı / cevap / bilgi notu) → generates the official letter with every mandatory element (başlık, sayı, tarih, konu, ilgi, gövde, imza bloğu with real names/titles from `users`, ek listesi) → **calls `check_letter_format` on its own draft → if elements are missing, revises and re-checks (max 3 revision rounds) → only then finishes**. Few-shot with correctly formatted example letters from the rules corpus. Regeneration bumps `drafts.version`; intermediate self-critique rounds do **not** create versions (they live in `tool_log`)
- [ ] **Cevap Ajanı — the human is a tool:** LangGraph `interrupt()` after delivery — graph sleeps until the recipient acts. On a short informal reply, `tools=[ask_user, get_document_context, search_rules, check_letter_format]`, `max_steps=5`: if required info is missing (deadline? addressee? decision?) it calls `ask_user` (max 2 rounds, enforced by the registry), pulls the original letter and the relevant rules for context, drafts the formal reply, format-checks it, then finishes → new `drafts` row → on user approval, `deliveries` row to the counterpart → graph resumes to `TAMAMLANDI`
- [ ] Delivery step: `deliveries` row = the in-app inbox (recipient's `email` shown on the envelope for realism; a real SMTP adapter stays behind a config flag, OFF by default — everything local)
- [ ] Full state machine enforced in one place: `ALINDI → OKUNDU → SINIFLANDIRILDI → ÖZETLENDİ → DOĞRULANDI → YÖNLENDİRİLDİ → TASLAK_HAZIR → TESLİM_EDİLDİ → YANIT_BEKLİYOR → YANITLANDI → TAMAMLANDI` (+ `TRİYAJ`, `İNCELEME_GEREKLİ`, `REDDEDİLDİ`); invalid transitions raise

**Quality gate (R2)**
- [ ] Extend eval harness: routing accuracy (vs `correct_department` labels) + **draft format compliance** — now measured by the *same* `check_letter_format` function the Yazıcı uses at runtime (so the metric and the tool can never drift apart)
- [ ] Extend dataset to ~100 docs including deliberately ambiguous routing cases (content overlapping two departments) **and a small set of documents whose correct routing is only obvious from precedent — these exist specifically to test `find_similar_past_docs`**
- [ ] **Tools A/B (the headline number):** routing accuracy and draft compliance with `TOOLS_ENABLED=0` vs `=1`, plus mean latency per stage. Report the trade-off honestly
- [ ] **Turkish drafting A/B:** load `Turkish-Gemma-9b-T1` into the ollama container via Modelfile (`scripts/pull-models.ps1` extension); 20 identical drafting jobs on `gemma4:12b` vs the 9B; blind scoring by all 4 members (formality/correctness/completeness, 1–5). Adopt the 9B as drafting model only if it wins by ≥0.5 average — otherwise stay single-model (VRAM swap costs latency). Record the decision in `docs/`

**UI (R3)**
- [ ] Gelen Kutusu: user-switcher dropdown (demo mode: act as any seeded user) · envelope list per user · open → summary + validation flags + draft + link to original
- [ ] Chat panel per document: message history · short-reply input · streamed rendering of the generated formal letter · **Onayla ve Gönder** button · follow-up-question bubbles when the agent calls `ask_user`
- [ ] **Routing card shows the evidence:** "Öğrenci İşleri'ne yönlendirildi — benzer bir dilekçe (12.03) aynı birime gitmişti" with a link to the precedent document

### Done when
- The full story runs from UI only: drop doc → … → recipient inbox → short chat reply → formal reply letter lands in the counterpart's inbox; routing accuracy and draft compliance numbers exist for **both tool modes**; the 12B-vs-9B decision is documented; **at least one node has been demoted back to single-shot if the A/B said so** (or we can explain why all five earned their loop).

---

## Phase 5 — Product experience: the app feels finished

**Goal:** Someone outside the team can use it unaided and nothing looks half-built. **The agent's reasoning becomes a visible product feature, not a log file.**
**Prerequisites:** Phase 3 done; Phase 4 in progress or done.

### Tasks
- [ ] **(R3)** Gelen Evrak dashboard: pipeline board — one column per status, document cards move live via SSE events; per-card elapsed/latency badge (near-real-time is a selling point — show it, don't claim it)
- [ ] **(R3)** Yönetim (Admin): CRUD for users & departments (edits re-embed department descriptions automatically) · rules manager: upload a new rule document → auto-chunk → auto-embed → **immediately searchable by `search_rules`, so validation uses it on the very next document with no restart**
- [ ] **(R3) Denetim Kaydı (Audit) — the reasoning trace screen (this is the "method depth" exhibit):** per-document timeline from `agent_log` + `tool_log` — for each agent: model, latency, tool steps, and each step as an expandable row *"🔎 search_rules('imza zorunluluğu dilekçe') → 3 sonuç · Madde 12, Madde 4"* with the agent's `thought_tr`. Degraded loops flagged in amber. Global filterable view. **Judges and users both see exactly how the system reached its conclusion**
- [ ] **(R3)** Turkish microcopy pass: every label, empty state, error, confirmation in clean formal Turkish; loading/streaming states everywhere — **including live tool-step status ("Kural aranıyor…", "Sayfa yeniden okunuyor…")**; no raw JSON or English leaks to the UI
- [ ] **(R4)** Settings (file + screen): model tag (12b ↔ e4b — maps to `MODEL_TAG`), Ollama URL, `manage_stack` on/off, SMTP flag, **`TOOLS_ENABLED` + `MAX_TOOL_STEPS` (labelled "Ajan modu: derin analiz / hızlı" — the honest UX framing of the latency trade-off, and the demo-day panic switch)**; persisted; applied on stack restart triggered from the settings screen
- [ ] **(R4)** Resilience: Docker not running → clear Turkish error screen with instructions; sidecar container crash → `restart: unless-stopped` brings it back + LangGraph checkpoint resume (document continues from the step it died on, not from zero — **including mid-tool-loop: the checkpoint stores the loop state**); ollama unreachable → clear Turkish error + retry
- [ ] **(R4)** In-app diagnostics panel: container status (compose ps), model list, last 50 sidecar log lines, **tool-call stats (calls/doc, failure rate, mean steps)** — the "easy to debug" promise, visible inside the app
- [ ] **(R1)** Prompt **and tool** hygiene: all prompts in versioned files with their schema documented; **tool descriptions live next to their implementation and are versioned the same way** (a tool description *is* a prompt); any prompt or tool-description change merges only with a fresh eval-harness run pasted into the PR

### Done when
- Each member does a 10-minute unscripted session (drop weird docs, click everything, reply in chat, open the reasoning trace on three documents, flip "Ajan modu" and feel the difference, `docker compose kill sidecar` mid-tool-loop and watch it resume) without hitting a broken state, raw JSON, or an English string.

---

## Phase 6 — Quality proof, hardening, release

**Goal:** Measured quality, crash-proof demo path, one-command install, publishable open-source repo.
**Prerequisites:** Phases 4 + 5.

### Tasks
- [ ] **(R2)** Freeze the 100-doc eval set; final metrics report (`docs/metrikler.md`, Turkish) as a **matrix**: classification accuracy · entity F1 · missing-info P/R · **citation groundedness & correctness** · routing accuracy · draft compliance % · summary rubric score · **mean tool steps · degraded-loop rate** · per-stage latency — for `gemma4:12b` vs `e4b`, **each with tools on and off (4 columns)**
- [ ] **(R2)** **The agentic-value section of the report:** one table, per node — "did the tool loop earn its latency?" Nodes that lost are shipped single-shot and *said so*. This section is the honest core of the "measured application quality" judging axis; a well-measured negative result beats an unmeasured claim
- [ ] **(R2)** Failure analysis: for every eval miss, one line — cause + fixed/wontfix; **for agentic nodes, include the trace: did it search the wrong thing, stop too early, or hallucinate a citation the groundedness check caught?** Feed quick prompt/tool-description fixes back through R1
- [ ] **(R4)** Demo image: build and tag the sidecar image (`docker-compose.demo.yml`), no mounts/debug; export with `docker save` to a `.tar` so demo machines need **no registry and no internet** to load it
- [ ] **(R4)** Offline proof: disable the network adapter → `docker compose -f docker-compose.yml -f docker-compose.demo.yml up` → run the entire flow end-to-end → record screen video (doubles as backup demo). Containers are local; nothing phones home — **every tool is a local DB/filesystem call, no tool touches the network. Say this out loud in the README: it is a genuine differentiator vs. cloud agent stacks**
- [ ] **(R4)** Fresh-machine install test: clean Windows machine → install Docker Desktop + Wails app installable (`wails build`) → `docker load` the image tar → load model volume (either `pull-models.ps1` or a pre-exported volume archive for fully-offline setup) → the 3-document scenario runs. Fix every manual step this reveals; prepare a second identical demo machine
- [ ] **(R1)** Scripted demo scenario (4 documents showing breadth): ① scanned petition with missing signature → **the Okuyucu zooms into the blurry signature block (visible in the trace)** → flagged + madde citation; ② digital official letter → routed **using precedent from document ①** + drafted + chat-reply round trip; ③ live rule upload in Admin → re-validate → **the Denetçi's `search_rules` finds the new rule and cites it, no restart**; ④ deliberately ambiguous document → Triyaj agent investigates, fails, escalates to a human **with its findings attached**. One command resets the DB volume to demo state (`scripts/demo-reset.ps1`)
- [ ] **(All)** Open-source packaging: license inventory of every dependency and base image; models NOT committed — link + version + license text + usage instructions in docs; Turkish README (kurulum = Docker Desktop + üç komut, mimari **+ the tool-loop diagram**, ekran görüntüleri); synthetic dataset + generator scripts included with data-source statements; repo made public under Apache-2.0 or MIT
- [ ] **(All)** Honest self-review against the four judging axes (method depth / measured application quality / demo clarity / originality) — fix the weakest axis first

### Done when
- A stranger with only Docker Desktop and the README can load the image, load the models, run the 4-document scenario, open the reasoning trace on any document, and open the metrics report — with the network cable unplugged.

---

## Working Agreements (entire project)

- **Same env is law:** all Python runs inside the sidecar container — never on the host. `uv.lock` + pinned image tags change only via PR. "Works on my machine" is answered with `docker compose logs`, not shrugs.
- **Git:** `main` protected; feature branches + one cross-role review; R4 merges. Small PRs over big ones.
- **Definition of done (any task):** merged + runs on a second member's machine via `docker compose up` + if it touches agent behavior, eval harness re-run (in-container, **both tool modes**) with numbers in the PR.
- **Prompts are code — and tool descriptions are prompts:** versioned files in the repo, schema documented next to each; no ad-hoc edits outside PRs.
- **Everything goes through `call_agent`.** No direct Ollama calls, no unregistered tools, no un-logged tool invocation. If it isn't in `tool_log`, it didn't happen.
- **Agentic is a means, not a goal.** A node gets a tool loop only if it faces an open-ended search/decision problem *and* the eval says the loop wins. Five nodes qualify today; a sixth needs evidence, and any of the five can be demoted.
- **Contracts first:** the Pydantic schemas (agent outputs) and the REST endpoints are the interfaces between R1/R3/R4 — change them only by agreement, announce in team chat. **The tool loop deliberately does not change these contracts: the final output object is identical whether tools ran or not.**
- **Scope discipline:** anything not in this document (audio input, e-signature integration, multi-tenant, cloud sync, write-tools that mutate the DB…) goes to `SONRA.md` — revisit only after Phase 6 is green.
- **Tools are read-only in v1.** No agent mutates state through a tool. All writes happen in graph nodes, in code, after the agent returns its typed answer. This makes every loop safe to retry and every eval run reproducible.
- **Data ethics:** no real personal or institutional data, ever; every external text source cited; only license-compatible dependencies.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| GPU-in-Docker fails on a member's machine (WSL2/driver issues) | Documented escape hatch: native host Ollama + `OLLAMA_URL=http://host.docker.internal:11434`; our code stays containerized either way |
| Bind-mount I/O slower on Windows/WSL2 | Only `/data` is bind-mounted (small files, DB); if DB latency ever matters, switch `data/db` to a named volume — one compose line |
| Gemma 4 formal Turkish (resmî üslup) not good enough | Phase 4 blind A/B gate with Turkish-Gemma-9b-T1; heavy few-shot with correctly formatted letters |
| 8 GB VRAM machines struggle with 12B | `MODEL_TAG=gemma4:e4b` env switch exists from Phase 1; latency for both measured in Phase 6 |
| OCR quality on bad scans | Normalization pass + **Okuyucu's `render_page` zoom loop** + eval set includes a deliberately bad scan |
| LLM JSON output instability breaks the pipeline | Single `call_agent` wrapper with schema validation + auto-retry-with-error; nothing bypasses it |
| **Tool loop doesn't converge / model never emits `finish`** | Hard `max_steps` + per-document tool budget + per-tool timeout → `degraded=true` → automatic fallback to the single-shot path. A stuck loop can never hang the pipeline; worst case we get today's behavior |
| **Small model calls tools badly (wrong args, invented tool names)** | Tool name is a `Literal` in the `AgentStep` schema (constrained decoding makes an invented name literally impossible); bad args → validation error fed back as the tool result, model retries; failure rate tracked in the diagnostics panel. If it stays high, that node is demoted to single-shot |
| **Agent cites a madde it never retrieved (hallucinated citation)** | Code-level groundedness check: citations not present in the tool trace are dropped and counted. Measured as `citation_groundedness` in every eval run |
| **Tool loops make the pipeline too slow for the demo** | Latency measured per node with tools on/off from Phase 2 onward; "Ajan modu: hızlı" setting (`TOOLS_ENABLED=0`) is a one-click demo-day fallback that still produces every artifact |
| **Non-determinism makes eval numbers noisy** | Fixed seed + temperature 0 for all agent calls; eval reports mean over 3 runs for agentic nodes; `tool_log` makes any regression diagnosable instead of mysterious |
| DuckDB write conflicts | Single uvicorn worker, one writer connection; decided in Phase 1, don't drift. **Tools are read-only, so no tool can ever contend for the write lock** |
| Demo-day failure | Checkpoint auto-resume (**including mid-tool-loop**) + `restart: unless-stopped` + offline video + one-command demo reset + `docker save` image tar + second prepared machine + `TOOLS_ENABLED=0` panic switch |
