from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

from openkb.storage import StorageBackend, get_backend

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Process-level settings resolved from environment variables.

    For local dev with Docker Compose use ``.env.docker``;
    for real Azure use ``.env.azure``.
    """

    storage_backend: str = "azure"
    openkb_base_dir: Path = Path.home() / ".local" / "share" / "openkb" / "kbs"
    azure_storage_connection_string: str = ""
    azure_kb_container: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("storage_backend")
    @classmethod
    def validate_storage_backend(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"local", "azure"}:
            raise ValueError("OPENKB_STORAGE_BACKEND must be 'local' or 'azure'")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


async def get_kb_backend(
    kb_name: str,
    settings: Settings | None = None,
) -> StorageBackend:
    """FastAPI dependency: resolve a StorageBackend for *kb_name*.

    Used as a FastAPI dependency via ``Depends(get_kb_backend)``. Each route
    passes ``kb_name`` either from the request body or as a query parameter.
    """
    if settings is None:
        settings = get_settings()
    return get_backend(kb_name, settings)
