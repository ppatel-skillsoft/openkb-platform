from __future__ import annotations

import os
from unittest.mock import patch

import pytest


_FULL_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=x;BlobEndpoint=http://localhost:10000/devstoreaccount1",
    "SIDECAR_CMD": "uvicorn openkb.api.app:app",
    "KB_ID": "00000000-0000-0000-0000-000000000001",
}


class TestWorkerConfig:
    def test_succeeds_with_all_required_vars(self, monkeypatch):
        for k, v in _FULL_ENV.items():
            monkeypatch.setenv(k, v)

        from compiler_worker.config import WorkerConfig
        config = WorkerConfig.from_env()

        assert config.database_url == _FULL_ENV["DATABASE_URL"]
        assert config.redis_url == _FULL_ENV["REDIS_URL"]
        assert config.blob_connection_string == _FULL_ENV["AZURE_STORAGE_CONNECTION_STRING"]
        assert config.sidecar_cmd == _FULL_ENV["SIDECAR_CMD"]
        assert config.kb_id == _FULL_ENV["KB_ID"]

    def test_raises_value_error_for_missing_required_var(self, monkeypatch):
        for k, v in _FULL_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("DATABASE_URL")

        from compiler_worker.config import WorkerConfig
        with patch("compiler_worker.config.load_dotenv"):
            with pytest.raises(ValueError, match="DATABASE_URL"):
                WorkerConfig.from_env()

    def test_raises_value_error_listing_multiple_missing_vars(self, monkeypatch):
        for k in _FULL_ENV:
            monkeypatch.delenv(k, raising=False)

        from compiler_worker.config import WorkerConfig
        with patch("compiler_worker.config.load_dotenv"):
            with pytest.raises(ValueError) as exc_info:
                WorkerConfig.from_env()
        error_msg = str(exc_info.value)
        for key in _FULL_ENV:
            assert key in error_msg

    def test_optional_vars_fall_back_to_defaults(self, monkeypatch):
        for k, v in _FULL_ENV.items():
            monkeypatch.setenv(k, v)
        for optional in ("QUEUE_KEY", "QUEUE_POLL_TIMEOUT_S", "SIDECAR_STARTUP_TIMEOUT_S",
                         "SIDECAR_COMPILE_TIMEOUT_S", "SIDECAR_POLL_INTERVAL_S", "LOG_LEVEL"):
            monkeypatch.delenv(optional, raising=False)

        from compiler_worker.config import WorkerConfig
        config = WorkerConfig.from_env()

        assert config.queue_key == "compiler:jobs"
        assert config.queue_poll_timeout == 5
        assert config.sidecar_startup_timeout == 15
        assert config.sidecar_compile_timeout == 300
        assert config.sidecar_poll_interval == 2.0
        assert config.log_level == "INFO"

    def test_optional_vars_can_be_overridden(self, monkeypatch):
        for k, v in _FULL_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("QUEUE_KEY", "my:queue")
        monkeypatch.setenv("QUEUE_POLL_TIMEOUT_S", "10")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        from compiler_worker.config import WorkerConfig
        config = WorkerConfig.from_env()

        assert config.queue_key == "my:queue"
        assert config.queue_poll_timeout == 10
        assert config.log_level == "DEBUG"
