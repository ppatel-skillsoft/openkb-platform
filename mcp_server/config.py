from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str  # Required: postgresql+asyncpg://...

    # ── Upstream service ─────────────────────────────────────────────────────
    generator_api_url: str = "http://generator-api:8001"

    # ── Server ───────────────────────────────────────────────────────────────
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8002

    # ── Timeouts ─────────────────────────────────────────────────────────────
    # query_timeout_s covers the full sidecar round-trip (blob sync + LLM call)
    query_timeout_s: float = 300.0

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
