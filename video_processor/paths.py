"""Path helpers shared between the CLI and the GUI.

The collection of final rendered clips for YouTube upload was previously
duplicated between :mod:`video_processor.cli` and :mod:`video_processor.ui`.
Centralizing it here keeps the glob pattern consistent across both surfaces.
"""

from __future__ import annotations

from pathlib import Path

from .config import PipelineConfig

__all__ = ["collect_upload_paths"]


def collect_upload_paths(config: PipelineConfig) -> list[Path]:
    """Collect rendered final clips from the pipeline output directory.

    Prefers subtitled files (``clip_*_sub.mp4``) when subtitle burning is on,
    otherwise returns plain ``clip_*.mp4`` files. Returns an empty list when
    the ``final/`` directory does not exist.
    """
    final_dir = config.output_dir / "final"
    if not final_dir.exists():
        return []
    # Prefer subtitled files; fall back to plain clips if subtitles are disabled.
    if config.burn_subs:
        return sorted(final_dir.glob("clip_*_sub.mp4"))
    clips = sorted(final_dir.glob("clip_*.mp4"))
    return [p for p in clips if not p.name.endswith("_sub.mp4")]
