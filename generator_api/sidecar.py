from __future__ import annotations

import logging
import os
import shlex
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx

from generator_api.exceptions import SidecarQueryError, SidecarStartError

logger = logging.getLogger(__name__)

_HEALTH_POLL_INTERVAL = 0.5
_TEARDOWN_WAIT_S = 5


def _allocate_port() -> int:
    """Return an available TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SidecarProcess:
    """Long-lived sidecar subprocess managed by SidecarPool."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._base_url: str | None = None
        self.last_used_at: float = time.monotonic()

    def is_healthy(self) -> bool:
        """Return True if the subprocess is running (non-blocking poll)."""
        return self._process is not None and self._process.poll() is None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start(
        self, scratch_dir: Path, kb_slug: str, llm_api_key: str, startup_timeout: int
    ) -> None:
        """Spawn the sidecar and wait for it to serve /openapi.json.

        Raises ``SidecarStartError`` if the sidecar is not ready within
        *startup_timeout* seconds.
        """
        self._port = _allocate_port()
        self._base_url = f"http://127.0.0.1:{self._port}"

        sidecar_env = {
            **os.environ,
            "STORAGE_BACKEND": "local",
            "OPENKB_BASE_DIR": str(scratch_dir),
            "OPENAI_API_KEY": llm_api_key,
            # Strip Azure env vars — sidecar must not accidentally write to blob
            "AZURE_STORAGE_CONNECTION_STRING": "",
            "AZURE_KB_CONTAINER": "",
        }

        cmd = shlex.split(f"openkb serve --host 127.0.0.1 --port {self._port}")
        logger.info("Starting sidecar on port %d (kb_slug=%s)", self._port, kb_slug)
        self._process = subprocess.Popen(
            cmd,
            cwd=str(scratch_dir),
            env=sidecar_env,
        )

        retries = int(startup_timeout / _HEALTH_POLL_INTERVAL)
        for attempt in range(retries):
            time.sleep(_HEALTH_POLL_INTERVAL)
            try:
                resp = httpx.get(f"{self._base_url}/openapi.json", timeout=2.0)
                if resp.status_code == 200:
                    logger.info(
                        "Sidecar healthy on port %d after %.1fs",
                        self._port,
                        (attempt + 1) * _HEALTH_POLL_INTERVAL,
                    )
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass

        raise SidecarStartError(
            f"Sidecar on port {self._port} did not become healthy within {startup_timeout}s"
        )

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def init(self, kb_slug: str) -> None:
        """Send POST /kb/init to register the KB in the sidecar."""
        resp = httpx.post(
            f"{self._base_url}/kb/init",
            json={"kb_name": kb_slug},
            timeout=30.0,
        )
        if resp.status_code not in (200, 409):  # 409 = already exists, idempotent
            raise SidecarQueryError(
                f"Sidecar init failed ({resp.status_code}): {resp.text}"
            )

    def query(self, kb_slug: str, question: str) -> tuple[str, list, int]:
        """Send POST /kb/query and return (answer, citations, tokens_used)."""
        resp = httpx.post(
            f"{self._base_url}/kb/query",
            json={"kb_name": kb_slug, "question": question, "save": False},
            timeout=300.0,
        )
        if resp.status_code != 200:
            raise SidecarQueryError(
                f"Sidecar query failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        return (
            data.get("answer", ""),
            data.get("citations", []),
            data.get("tokens_used", 0),
        )

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def teardown(self) -> None:
        """Send SIGTERM; wait up to 5s; SIGKILL if still running."""
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
