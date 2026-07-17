"""Progress reporting helpers used by both the CLI and the GUI."""

from __future__ import annotations

from enum import Enum
from typing import Protocol


class Step(Enum):
    SEGMENT = "segment"
    TRANSCRIBE = "transcribe"
    BURN = "burn"
    CONVERT = "convert"
    DOWNLOAD = "download"
    UPLOAD = "upload"
    DONE = "done"


class ProgressCallback(Protocol):
    """Protocol for progress callbacks."""

    def __call__(self, step: Step, current: int, total: int, message: str) -> None: ...


def noop_progress(step: Step, current: int, total: int, message: str) -> None:
    """Default progress callback that does nothing."""
    pass


def default_message(step: Step, current: int, total: int, message: str) -> str:
    """Build a domain-neutral, consistently indexed progress message."""
    if total <= 0:
        return f"{step.value}: {message}"
    position = total if step is Step.DONE else min(max(current + 1, 1), total)
    return f"[{position}/{total}] {step.value}: {message}"
