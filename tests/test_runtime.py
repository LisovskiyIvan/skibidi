"""Tests for bounded, cancellable subprocess execution."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from video_processor.errors import PipelineError, ProcessCancelledError, ProcessTimeoutError
from video_processor.runtime import run_process


def test_stdout_is_devnull_by_default() -> None:
    result = run_process(
        [sys.executable, "-c", "print('ignored')"],
        timeout=5,
    )
    assert result.stdout == ""


def test_stdout_can_be_captured() -> None:
    result = run_process(
        [sys.executable, "-c", "print('json')"],
        timeout=5,
        capture_stdout=True,
    )
    assert result.stdout == "json\n"


def test_failure_stderr_is_bounded() -> None:
    with pytest.raises(PipelineError) as raised:
        run_process(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('START' + 'x' * 5000 + 'END'); sys.exit(2)",
            ],
            timeout=5,
            stderr_limit=1024,
        )
    message = str(raised.value)
    stderr = message.split("STDERR (tail):", 1)[1]
    assert "START" not in stderr
    assert "END" in stderr
    assert len(message) < 1400


def test_timeout_terminates_process() -> None:
    with pytest.raises(ProcessTimeoutError, match="timed out"):
        run_process(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=0.05,
        )


def test_cancellation_terminates_process() -> None:
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ProcessCancelledError, match="cancelled"):
        run_process(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=5,
            cancel_event=cancelled,
        )


def test_launch_error_is_wrapped(tmp_path: Path) -> None:
    missing = tmp_path / "missing-command"
    with pytest.raises(PipelineError, match="Could not launch"):
        run_process([str(missing)], timeout=5)


def test_stderr_callback_receives_lines() -> None:
    lines: list[str] = []
    run_process(
        [sys.executable, "-c", "import sys; print('progress=1', file=sys.stderr)"],
        timeout=5,
        on_stderr_line=lines.append,
    )
    assert lines == ["progress=1"]


def test_stderr_callback_failure_stops_process() -> None:
    def fail(_line: str) -> None:
        raise PipelineError("callback stopped")

    with pytest.raises(PipelineError, match="callback stopped"):
        run_process(
            [
                sys.executable,
                "-c",
                "import sys,time; print('progress=1', file=sys.stderr, flush=True); time.sleep(10)",
            ],
            timeout=2,
            on_stderr_line=fail,
        )


def test_process_uses_devnull_stdin_and_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import patch

    with patch("video_processor.runtime.subprocess.Popen", wraps=subprocess.Popen) as popen:
        run_process([sys.executable, "-c", "pass"], timeout=5)
    options = popen.call_args.kwargs
    assert options["stdin"] is subprocess.DEVNULL
    assert options["stdout"] is subprocess.DEVNULL
