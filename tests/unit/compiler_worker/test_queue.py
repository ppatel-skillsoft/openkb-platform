from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from compiler_worker.queue_client import RedisQueueClient, parse_job
from compiler_worker.models import CompilationJob

_VALID_RAW = (
    '{"job_id":"j1","kb_id":"kb1","document_id":"d1",'
    '"blob_path":"kb-kb1/raw/f.md","filename":"f.md","enqueued_at":"2026-01-01T00:00:00Z"}'
)


class TestRedisQueueClient:
    def test_dequeue_returns_json_when_brpop_has_value(self):
        mock_redis = MagicMock()
        mock_redis.brpop.return_value = ("compiler:jobs", _VALID_RAW)

        with patch("redis.from_url", return_value=mock_redis):
            client = RedisQueueClient("redis://localhost", "compiler:jobs")
            result = client.dequeue(5)

        assert result == _VALID_RAW

    def test_dequeue_returns_none_on_timeout(self):
        mock_redis = MagicMock()
        mock_redis.brpop.return_value = None

        with patch("redis.from_url", return_value=mock_redis):
            client = RedisQueueClient("redis://localhost", "compiler:jobs")
            result = client.dequeue(5)

        assert result is None


class TestParseJob:
    def test_returns_compilation_job_for_valid_json(self):
        job = parse_job(_VALID_RAW)
        assert isinstance(job, CompilationJob)
        assert job.job_id == "j1"
        assert job.kb_id == "kb1"
        assert job.document_id == "d1"

    def test_returns_none_for_malformed_json(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR):
            result = parse_job("not-json{{{")
        assert result is None
        assert "invalid JSON" in caplog.text or "malformed" in caplog.text.lower()

    def test_returns_none_for_missing_required_field(self, caplog):
        import logging, json
        data = json.loads(_VALID_RAW)
        del data["job_id"]
        with caplog.at_level(logging.ERROR):
            result = parse_job(json.dumps(data))
        assert result is None
        assert "missing" in caplog.text.lower() or "field" in caplog.text.lower()

    def test_returns_none_for_multiple_missing_fields(self):
        result = parse_job("{}")
        assert result is None
