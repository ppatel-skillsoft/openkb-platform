from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str  # Required: postgresql+asyncpg://...

    # ── Blob Storage ─────────────────────────────────────────────────────────
    azure_storage_connection_string: str  # Required: Azurite or Azure conn string
    azure_kb_container: str = "openkb"

    # ── LLM (forwarded to sidecar subprocess) ────────────────────────────────
    llm_api_key: str = ""  # Warn if empty; service starts but queries will fail

    # ── Sidecar ──────────────────────────────────────────────────────────────
    sidecar_startup_timeout: int = 30   # Seconds to wait for sidecar readiness
    generator_request_timeout: int = 300  # Seconds before HTTP 504

    # ── Scratch Storage ───────────────────────────────────────────────────────
    scratch_dir_root: Path = Path("/tmp/generator-scratch")

    # ── Server ───────────────────────────────────────────────────────────────
    generator_host: str = "0.0.0.0"
    generator_port: int = 8001

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
