"""Central config, read once from the environment. Never hardcode a model tag."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    ollama_url: str = "http://ollama:11434"
    model_tag: str = "gemma3:12b"
    model_tag_fallback: str = "gemma3:4b"
    embed_model_tag: str = "bge-m3"

    tools_enabled: bool = True
    max_tool_steps: int = 5
    tool_budget_per_doc: int = 20

    db_path: str = "/data/db/evrak.duckdb"
    storage_path: str = "/data/storage"
    rules_path: str = "/data/rules"

    api_host: str = "0.0.0.0"
    api_port: int = 8756

    # Number of extracted text-layer chars below which a PDF is treated as scanned.
    scanned_char_threshold: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
