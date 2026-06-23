from __future__ import annotations

import signal
import subprocess
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from compiler_worker.sidecar import SidecarProcess, allocate_port


class TestAllocatePort:
    def test_returns_integer(self):
        port = allocate_port()
        assert isinstance(port, int)

    def test_port_in_valid_range(self):
        port = allocate_port()
        assert 1 <= port <= 65535


class TestSidecarStart:
    def test_start_succeeds_when_health_returns_200(self, tmp_path):
        from compiler_worker.config import WorkerConfig

        config = WorkerConfig(
            database_url="postgresql+asyncpg://x:x@localhost/x",
            blob_connection_string="conn",
            sidecar_cmd="python -m http.server",
            kb_id="test-kb",
            sidecar_startup_timeout=15,
        )

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("httpx.get", return_value=mock_response), \
             patch("compiler_worker.sidecar.allocate_port", return_value=9999):
            sidecar = SidecarProcess()
            sidecar.start(config, tmp_path)

        mock_popen.assert_called_once()
        cmd_used = mock_popen.call_args[0][0]
        assert "--host" in cmd_used
        assert "--port" in cmd_used
        assert "9999" in cmd_used

    def test_start_raises_when_health_never_200(self, tmp_path):
        from compiler_worker.config import WorkerConfig
        from compiler_worker.exceptions import SidecarStartError

        config = WorkerConfig(
            database_url="postgresql+asyncpg://x:x@localhost/x",
            blob_connection_string="conn",
            sidecar_cmd="python -m http.server",
            kb_id="test-kb",
        )

        mock_proc = MagicMock(spec=subprocess.Popen)
        import httpx as httpx_lib

        with patch("subprocess.Popen", return_value=mock_proc), \
             patch("httpx.get", side_effect=httpx_lib.ConnectError("refused")), \
             patch("compiler_worker.sidecar.allocate_port", return_value=9999), \
             patch("time.sleep"):
            sidecar = SidecarProcess()
            with pytest.raises(SidecarStartError):
                sidecar.start(config, tmp_path)


class TestSidecarTeardown:
    def test_sends_sigterm_then_sigkill_if_not_exited(self, tmp_path):
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=5), None]

        sidecar = SidecarProcess()
        sidecar._process = mock_proc
        sidecar._base_url = "http://127.0.0.1:9999"
        sidecar._port = 9999

        sidecar.teardown()

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
        mock_proc.kill.assert_called_once()

    def test_sigterm_only_when_process_exits_cleanly(self):
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345

        sidecar = SidecarProcess()
        sidecar._process = mock_proc
        sidecar._base_url = "http://127.0.0.1:9999"
        sidecar._port = 9999

        sidecar.teardown()

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
        mock_proc.kill.assert_not_called()


class TestGetStatusDeserialisation:
    def _make_sidecar_with_base_url(self, base_url: str) -> SidecarProcess:
        s = SidecarProcess()
        s._base_url = base_url
        return s

    @pytest.mark.parametrize("status_value", ["idle", "compiling", "complete"])
    def test_deserialises_non_failed_statuses(self, status_value):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": status_value,
            "pages": [],
            "token_cost": None,
            "pageindex_used": None,
            "error": None,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            sidecar = self._make_sidecar_with_base_url("http://127.0.0.1:9999")
            result = sidecar.get_status()

        assert result.status == status_value

    def test_raises_sidecar_compile_error_on_failed(self):
        from compiler_worker.exceptions import SidecarCompileError

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "failed",
            "pages": [],
            "token_cost": None,
            "pageindex_used": None,
            "error": "LLM error",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            sidecar = self._make_sidecar_with_base_url("http://127.0.0.1:9999")
            with pytest.raises(SidecarCompileError) as exc_info:
                sidecar.get_status()

        assert "LLM error" in str(exc_info.value)
