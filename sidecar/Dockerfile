# Reproducible, byte-for-byte image: pinned base + `uv sync --frozen` against uv.lock.
FROM python:3.12-slim

# System libs PyMuPDF needs at runtime + curl for the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

# uv: fast, deterministic installs. Copy the static binary from the official image.
COPY --from=ghcr.io/astral-sh/uv:0.7.17 /uv /uvx /bin/

WORKDIR /app

# Install deps first (better layer caching). Only lockfiles => cache survives code edits.
# Dev group (pytest/ruff) is included so the eval harness + tests run IN-CONTAINER, offline,
# as the non-root user — which the working agreement requires (never run Python on the host).
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-install-project

# App code (in dev this is shadowed by the ./sidecar bind mount for hot reload).
COPY . .

# Non-root runtime user; /data is bind-mounted and owned by the host, so keep it writable.
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8756
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8756/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8756"]
