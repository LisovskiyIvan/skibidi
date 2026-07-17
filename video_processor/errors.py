"""Shared exception types for the pipeline.

Lives in its own module so that low-level helpers (``ffmpeg``) can raise
``PipelineError`` without importing the orchestrator (``pipeline``) and
creating a circular import.
"""

from __future__ import annotations


class PipelineError(Exception):
    """Raised when a pipeline step fails.

    Operational/expected failures (missing input, ffmpeg returning a non-zero
    exit code, unreadable media) should raise this so the CLI can report them
    cleanly. Unexpected exceptions surface as generic errors.
    """

    pass


class ProcessTimeoutError(PipelineError):
    """Raised when an external command exceeds its configured deadline."""


class ProcessCancelledError(PipelineError):
    """Raised when cooperative cancellation stops an external command."""
