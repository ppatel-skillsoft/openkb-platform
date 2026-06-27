"""Unit tests for SidecarProcess.is_healthy() — T006."""

from __future__ import annotations

from unittest.mock import MagicMock

from generator_api.sidecar import SidecarProcess


def test_is_healthy_before_start_returns_false() -> None:
    sidecar = SidecarProcess()
    assert sidecar.is_healthy() is False


def test_is_healthy_after_process_exits_returns_false() -> None:
    sidecar = SidecarProcess()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0  # process exited (returncode 0)
    sidecar._process = mock_proc
    assert sidecar.is_healthy() is False


def test_is_healthy_while_process_running_returns_true() -> None:
    sidecar = SidecarProcess()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # process still alive
    sidecar._process = mock_proc
    assert sidecar.is_healthy() is True


def test_last_used_at_initialised_on_construction() -> None:
    import time

    before = time.monotonic()
    sidecar = SidecarProcess()
    after = time.monotonic()
    assert before <= sidecar.last_used_at <= after
