from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_REQUIRED = [
    "DATABASE_URL",
    "AZURE_STORAGE_CONNECTION_STRING",
    "SIDECAR_CMD",
    "KB_ID",
]


@dataclass
class WorkerConfig:
    """All runtime configuration for the compiler-worker.

    Load via ``WorkerConfig.from_env()``; raises ``ValueError`` immediately if
    any required environment variable is absent.
    """

    database_url: str
    redis_url: str
    blob_connection_string: str
    sidecar_cmd: str
    kb_id: str

    queue_backend: str = "postgres"  # "postgres" (default) or "redis" (opt-in)
    queue_key: str = "compiler:jobs"
    queue_poll_timeout: int = 5
    sidecar_startup_timeout: int = 15
    sidecar_compile_timeout: int = 300
    sidecar_poll_interval: float = 2.0
    log_level: str = "INFO"
    # When set, tempfile.mkdtemp is called with dir=scratch_dir_root so that
    # per-job scratch directories are created under this path. This allows a
    # shared Docker volume to be mounted here, making scratch dirs visible to
    # the isolation-tests container (spec 006 FR-007).
    scratch_dir_root: Path | None = None

    @classmethod
    def from_env(cls) -> WorkerConfig:
        """Read config from environment variables.

        Calls ``load_dotenv()`` first so a ``.env`` file in the working
        directory is picked up automatically.  Raises ``ValueError`` listing
        all missing required variables.
        """
        load_dotenv()
        missing = [k for k in _REQUIRED if not os.environ.get(k)]
        if missing:
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")
        return cls(
            database_url=os.environ["DATABASE_URL"],
            redis_url=os.environ.get("REDIS_URL", ""),
            blob_connection_string=os.environ["AZURE_STORAGE_CONNECTION_STRING"],
            sidecar_cmd=os.environ["SIDECAR_CMD"],
            kb_id=os.environ["KB_ID"],
            queue_backend=os.environ.get("QUEUE_BACKEND", "postgres"),
            queue_key=os.environ.get("QUEUE_KEY", "compiler:jobs"),
            queue_poll_timeout=int(os.environ.get("QUEUE_POLL_TIMEOUT_S", "5")),
            sidecar_startup_timeout=int(
                os.environ.get("SIDECAR_STARTUP_TIMEOUT_S", "15")
            ),
            sidecar_compile_timeout=int(
                os.environ.get("SIDECAR_COMPILE_TIMEOUT_S", "300")
            ),
            sidecar_poll_interval=float(
                os.environ.get("SIDECAR_POLL_INTERVAL_S", "2.0")
            ),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            scratch_dir_root=(
                Path(v) if (v := os.environ.get("COMPILER_WORKER_SCRATCH_ROOT")) else None
            ),
        )
