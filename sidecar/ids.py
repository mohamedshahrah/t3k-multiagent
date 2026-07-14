"""UUIDv7 helpers. Time-ordered ids keep rows naturally sorted by creation."""
from __future__ import annotations

import uuid

import uuid_utils


def new_uuid7() -> uuid.UUID:
    """A stdlib uuid.UUID (v7). DuckDB binds stdlib UUIDs into UUID columns natively."""
    return uuid.UUID(str(uuid_utils.uuid7()))
