"""Shared helper for optional-dependency guards.

Several features (YouTube upload, YouTube download, faster-whisper STT) depend
on packages that are not installed by default. Each feature module used to
duplicate a ``_ensure_deps()`` shim that raised a feature-specific error when
its dependency was missing. This module centralizes the raise logic so the
feature modules only need to declare their availability flag and install hint.
"""

from __future__ import annotations

from .errors import PipelineError

__all__ = ["ensure_optional_dep"]


def ensure_optional_dep(available: bool, dep_name: str, install_hint: str) -> None:
    """Raise a :class:`PipelineError` when ``available`` is false.

    Parameters
    ----------
    available:
        Whether the optional dependency is importable.
    dep_name:
        Human-readable name of the feature/dependency, e.g. ``"YouTube upload"``.
    install_hint:
        Concrete install command the user should run, e.g.
        ``pip install -e '.[youtube]'``.
    """
    if not available:
        raise PipelineError(f"{dep_name} is not installed. Install with: {install_hint}")
