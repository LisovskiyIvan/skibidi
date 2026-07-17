"""Bounded, cancellable subprocess execution used by core media helpers."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .errors import PipelineError, ProcessCancelledError, ProcessTimeoutError


@dataclass(frozen=True)
class ProcessResult:
    """Useful output from a successfully completed process."""

    stdout: str
    stderr: str


class _TailBuffer:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._value = ""
        self._lock = threading.Lock()

    def append(self, value: str) -> None:
        with self._lock:
            self._value = (self._value + value)[-self._limit :]

    def get(self) -> str:
        with self._lock:
            return self._value


def _command_message(cmd: list[str], stderr: str) -> str:
    return f"Command failed:\n{shlex.join(cmd)}\n\nSTDERR (tail):\n{stderr}"


def _stop_process(process: subprocess.Popen[str], *, force: bool = False) -> None:
    """Stop the child and its POSIX process group when one was created."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            process.kill()
        else:
            process.terminate()
    except (OSError, ProcessLookupError):
        pass


def run_process(
    cmd: list[str],
    *,
    timeout: float,
    stderr_limit: int = 64 * 1024,
    capture_stdout: bool = False,
    cancel_event: threading.Event | None = None,
    on_stderr_line: Callable[[str], None] | None = None,
) -> ProcessResult:
    """Run a process with bounded diagnostics, timeout, and cancellation.

    Standard output is discarded unless explicitly requested. Both output
    streams are drained concurrently so a noisy child cannot deadlock.
    """
    if not cmd:
        raise PipelineError("Cannot launch an empty command")
    start_new_session = os.name == "posix"
    creationflags = (
        int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0
    )

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            bufsize=1,
            start_new_session=start_new_session,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise PipelineError(f"Could not launch {cmd[0]!r}: {exc}") from exc

    stderr = _TailBuffer(stderr_limit)
    stdout_parts: list[str] = []
    reader_errors: list[BaseException] = []

    def read_stderr() -> None:
        assert process.stderr is not None
        try:
            for line in process.stderr:
                stderr.append(line)
                if on_stderr_line is not None:
                    on_stderr_line(line.rstrip("\r\n"))
        except BaseException as exc:
            reader_errors.append(exc)

    def read_stdout() -> None:
        assert process.stdout is not None
        try:
            for chunk in process.stdout:
                stdout_parts.append(chunk)
        except BaseException as exc:
            reader_errors.append(exc)

    threads = [threading.Thread(target=read_stderr, daemon=True)]
    if capture_stdout:
        threads.append(threading.Thread(target=read_stdout, daemon=True))
    for thread in threads:
        thread.start()

    started = time.monotonic()
    stopped_for: str | None = None
    try:
        while process.poll() is None:
            if reader_errors:
                stopped_for = "reader_error"
                _stop_process(process)
                break
            if cancel_event is not None and cancel_event.is_set():
                stopped_for = "cancelled"
                _stop_process(process)
                break
            if time.monotonic() - started >= timeout:
                stopped_for = "timeout"
                _stop_process(process)
                break
            time.sleep(0.05)

        if stopped_for is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _stop_process(process, force=True)
                process.wait()
        else:
            process.wait()
    finally:
        for thread in threads:
            thread.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    stderr_text = stderr.get()
    if reader_errors:
        raise reader_errors[0]
    if stopped_for == "cancelled":
        raise ProcessCancelledError(f"Command cancelled: {shlex.join(cmd)}")
    if stopped_for == "timeout":
        raise ProcessTimeoutError(
            f"Command timed out after {timeout:g}s: {shlex.join(cmd)}\n"
            f"STDERR (tail):\n{stderr_text}"
        )
    if process.returncode != 0:
        raise PipelineError(_command_message(cmd, stderr_text))
    return ProcessResult(stdout="".join(stdout_parts), stderr=stderr_text)
