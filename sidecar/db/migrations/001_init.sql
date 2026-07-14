-- Schema v1. Applied once by the migration runner (records itself in schema_migrations).
-- Identity: UUIDv7 primary keys (generated in Python) + SHA-256 for duplicate rejection.

-- Sequences for the integer-keyed reference tables.
CREATE SEQUENCE IF NOT EXISTS seq_rules_chunks START 1;

CREATE TABLE IF NOT EXISTS documents (
    id           UUID PRIMARY KEY,
    sha256       TEXT UNIQUE,
    filename     TEXT,
    mime         TEXT,
    source_path  TEXT,
    page_count   INTEGER,
    is_scanned   BOOLEAN,
    status       TEXT,
    received_at  TIMESTAMP DEFAULT now(),
    raw_text     TEXT
);

CREATE TABLE IF NOT EXISTS pages (
    doc_id        UUID,
    page_no       INTEGER,
    text          TEXT,
    image_path    TEXT,
    has_signature BOOLEAN,
    has_stamp     BOOLEAN
);

CREATE TABLE IF NOT EXISTS classifications (
    doc_id     UUID,
    doc_type   TEXT,
    confidence FLOAT,
    entities   JSON
);

CREATE TABLE IF NOT EXISTS summaries (
    doc_id     UUID,
    summary_tr TEXT,
    one_liner  TEXT,
    model      TEXT,
    latency_ms INTEGER
);

CREATE TABLE IF NOT EXISTS validations (
    doc_id        UUID,
    is_compliant  BOOLEAN,
    missing_fields JSON,
    matched_rules JSON,
    report_tr     TEXT
);

CREATE TABLE IF NOT EXISTS routings (
    doc_id        UUID,
    department_id INTEGER,
    user_id       INTEGER,
    rationale_tr  TEXT,
    confidence    FLOAT
);

CREATE TABLE IF NOT EXISTS drafts (
    id         UUID PRIMARY KEY,
    doc_id     UUID,
    draft_type TEXT,
    content_tr TEXT,
    version    INTEGER,
    status     TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    name          TEXT,
    email         TEXT,
    title         TEXT,
    department_id INTEGER
);

CREATE TABLE IF NOT EXISTS departments (
    id                 INTEGER PRIMARY KEY,
    name               TEXT,
    responsibilities_tr TEXT,
    embedding          FLOAT[1024]
);

CREATE TABLE IF NOT EXISTS rules_chunks (
    id        INTEGER PRIMARY KEY DEFAULT nextval('seq_rules_chunks'),
    source    TEXT,
    madde_no  TEXT,
    doc_types JSON,
    text_tr   TEXT,
    embedding FLOAT[1024]
);

CREATE TABLE IF NOT EXISTS doc_type_requirements (
    doc_type          TEXT PRIMARY KEY,
    required_elements JSON
);

CREATE TABLE IF NOT EXISTS deliveries (
    id           UUID PRIMARY KEY,
    doc_id       UUID,
    draft_id     UUID,
    to_user_id   INTEGER,
    status       TEXT,
    delivered_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id      UUID PRIMARY KEY,
    doc_id  UUID,
    user_id INTEGER,
    role    TEXT,
    content TEXT,
    ts      TIMESTAMP DEFAULT now()
);

-- One row per agent call. Gains the agentic columns (tool_steps, degraded).
CREATE TABLE IF NOT EXISTS agent_log (
    id             UUID PRIMARY KEY,
    doc_id         UUID,
    agent          TEXT,
    model          TEXT,
    input_summary  TEXT,
    output_summary TEXT,
    tool_steps     INTEGER,   -- how many loop iterations
    degraded       BOOLEAN,   -- loop failed -> single-shot fallback used
    latency_ms     INTEGER,
    ts             TIMESTAMP DEFAULT now()
);

-- One row per tool invocation = the reasoning trace shown on the audit screen.
CREATE TABLE IF NOT EXISTS tool_log (
    id             UUID PRIMARY KEY,
    doc_id         UUID,
    agent_log_id   UUID,
    step_no        INTEGER,
    tool           TEXT,
    thought_tr     TEXT,
    args           JSON,
    result_summary TEXT,
    ok             BOOLEAN,
    latency_ms     INTEGER,
    ts             TIMESTAMP DEFAULT now()
);
