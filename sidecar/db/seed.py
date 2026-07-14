"""Seed demo departments + users (idempotent).

Run inside the container:  docker compose exec sidecar python -m db.seed
Reads data/seeds/*.json (bind-mounted at /data/seeds). Department embeddings are left
NULL here and populated in Phase 3 by rag.embed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from db.connection import execute
from db.migrate import run_migrations

log = logging.getLogger("evrak.seed")

SEEDS_DIR = Path("/data/seeds")


def _load(name: str) -> list[dict]:
    return json.loads((SEEDS_DIR / name).read_text(encoding="utf-8"))


def seed() -> None:
    run_migrations()
    departments = _load("departments.json")
    users = _load("users.json")

    execute("DELETE FROM users")
    execute("DELETE FROM departments")

    for d in departments:
        execute(
            "INSERT INTO departments (id, name, responsibilities_tr) VALUES (?, ?, ?)",
            [d["id"], d["name"], d["responsibilities_tr"]],
        )
    for u in users:
        execute(
            "INSERT INTO users (id, name, email, title, department_id) VALUES (?, ?, ?, ?, ?)",
            [u["id"], u["name"], u["email"], u["title"], u["department_id"]],
        )
    log.info("seeded %d departments, %d users", len(departments), len(users))
    print(f"seeded {len(departments)} departments, {len(users)} users")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed()
