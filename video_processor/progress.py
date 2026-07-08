"""Progress reporting helpers used by both the CLI and the GUI."""

from __future__ import annotations

from enum import Enum
from typing import Callable, Protocol


class Step(Enum):
    SEGMENT = "segment"
    TRANSCRIBE = "transcribe"
    BURN = "burn"
    CONVERT = "convert"
    DONE = "done"


class ProgressCallback(Protocol):
    """Protocol for progress callbacks."""

    def __call__(self, step: Step, current: int, total: int, message: str) -> None:
        ...


def noop_progress(step: Step, current: int, total: int, message: str) -> None:
    """Default progress callback that does nothing."""
    pass


StepFormatter = Callable[[Step, int, int, str], str]


def default_message(step: Step, current: int, total: int, message: str) -> str:
    """Build a human-readable progress message."""
    if step is Step.DONE:
        return f"Done. Total segments: {total}."
    return f"[{current + 1}/{total}] {step.value}: {message}"
