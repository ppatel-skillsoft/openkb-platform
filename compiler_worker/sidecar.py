from __future__ import annotations

import logging
import shlex
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx

from compiler_worker.config import WorkerConfig
from compiler_worker.models import SidecarPage, SidecarStatus

logger = logging.getLogger(__name__)

_HEALTH_POLL_RETRIES = 30
_HEALTH_POLL_INTERVAL = 0.5
_TEARDOWN_WAIT_S = 5


def allocate_port() -> int:
    """Ask the OS for a free TCP port and return it immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


class SidecarProcess:
    """Manages the lifecycle of a per-job sidecar FastAPI process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._base_url: str | None = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start(self, config: WorkerConfig, scratch_dir: Path) -> None:
        """Spawn the sidecar and wait for its ``/health`` endpoint to respond.

        Raises ``SidecarStartError`` if the health check never succeeds within
        the configured timeout.
        """
        # Import here to avoid circular dependency with exceptions module
        from compiler_worker.exceptions import SidecarStartError

        self._port = allocate_port()
        self._base_url = f"http://127.0.0.1:{self._port}"

        cmd = shlex.split(config.sidecar_cmd) + [
            "--host",
            "127.0.0.1",
            "--port",
            str(self._port),
        ]
        logger.info("Starting sidecar on port %d: %s", self._port, " ".join(cmd))
        self._process = subprocess.Popen(cmd, cwd=str(scratch_dir))

        # Poll /health
        for attempt in range(_HEALTH_POLL_RETRIES):
            time.sleep(_HEALTH_POLL_INTERVAL)
            try:
                resp = httpx.get(f"{self._base_url}/health", timeout=2.0)
                if resp.status_code == 200:
                    logger.info(
                        "Sidecar healthy on port %d after %d attempts",
                        self._port,
                        attempt + 1,
                    )
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass

        raise SidecarStartError(
            f"Sidecar on port {self._port} did not become healthy within "
            f"{_HEALTH_POLL_RETRIES * _HEALTH_POLL_INTERVAL:.1f}s"
        )

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def init(self, model: str, language: str) -> None:
        """Send ``POST /init`` to the sidecar. Raises on non-2xx."""
        resp = httpx.post(
            f"{self._base_url}/init",
            json={"model": model, "language": language},
            timeout=30.0,
        )
        resp.raise_for_status()

    def add(self, filename: str) -> None:
        """Send ``POST /add`` to the sidecar. Raises on non-2xx."""
        resp = httpx.post(
            f"{self._base_url}/add",
            json={"filename": filename},
            timeout=30.0,
        )
        resp.raise_for_status()

    def get_status(self) -> SidecarStatus:
        """Send ``GET /status`` and return a ``SidecarStatus``. Raises on non-2xx."""
        from compiler_worker.exceptions import SidecarCompileError

        resp = httpx.get(f"{self._base_url}/status", timeout=60.0)
        resp.raise_for_status()
        data = resp.json()

        pages = [
            SidecarPage(
                slug=p["slug"],
                page_type=p["page_type"],
                entity_type=p.get("entity_type"),
                file_path=p["file_path"],
            )
            for p in data.get("pages", [])
        ]
        status = SidecarStatus(
            status=data["status"],
            pages=pages,
            token_cost=data.get("token_cost"),
            pageindex_used=data.get("pageindex_used"),
            error=data.get("error"),
        )
        if status.status == "failed":
            raise SidecarCompileError(
                status.error or "Sidecar reported compilation failure"
            )
        return status

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def teardown(self) -> None:
        """Send SIGTERM; wait up to 5 s; send SIGKILL if still running."""
        if self._process is None:
            return
        proc = self._process
        self._process = None
        self._base_url = None
        self._port = None

        if proc.poll() is not None:
            return

        logger.debug("Sending SIGTERM to sidecar PID %d", proc.pid)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=_TEARDOWN_WAIT_S)
        except subprocess.TimeoutExpired:
            logger.warning("Sidecar PID %d did not exit; sending SIGKILL", proc.pid)
            proc.kill()
            proc.wait()
