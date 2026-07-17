"""Path helpers shared between the CLI and the GUI.

The collection of final rendered clips for YouTube upload was previously
duplicated between :mod:`video_processor.cli` and :mod:`video_processor.ui`.
Centralizing it here keeps the glob pattern consistent across both surfaces.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import PipelineConfig

__all__ = ["collect_upload_paths", "sort_clip_paths"]

_CLIP_NUMBER = re.compile(r"(?:^|_)clip_(\d+)(?:_|\.)", re.IGNORECASE)


def sort_clip_paths(paths: list[Path]) -> list[Path]:
    """Sort numbered clip names numerically, with stable lexical fallbacks."""

    def key(path: Path) -> tuple[int, int, str]:
        match = _CLIP_NUMBER.search(path.name)
        if match:
            return (0, int(match.group(1)), path.name.casefold())
        return (1, 0, path.name.casefold())

    return sorted(paths, key=key)


def collect_upload_paths(config: PipelineConfig) -> list[Path]:
    """Collect rendered final clips from the pipeline output directory.

    Prefers subtitled files (``clip_*_sub.mp4``) when subtitle burning is on,
    otherwise returns plain ``clip_*.mp4`` files. Returns an empty list when
    the ``final/`` directory does not exist.
    """
    final_dir = config.output_dir / "final"
    if not final_dir.exists():
        return []
    manifest_path = final_dir / "resume-manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("version") != 2:
                return []
            total_segments = manifest.get("total_segments")
            segments = manifest.get("segments", {})
            if not isinstance(total_segments, int) or total_segments < 0:
                return []
            if not isinstance(segments, dict):
                return []
            suffix = "_sub.mp4" if config.burn_subs else ".mp4"
            current: list[Path] = []
            for idx in range(total_segments):
                expected = final_dir / f"clip_{idx:02d}{suffix}"
                entry = segments.get(str(idx))
                if not isinstance(entry, dict) or entry.get("name") != expected.name:
                    return []
                if not expected.is_file():
                    return []
                current.append(expected)
            return current
        except (AttributeError, json.JSONDecodeError, OSError, TypeError):
            return []
    # Prefer subtitled files; fall back to plain clips if subtitles are disabled.
    if config.burn_subs:
        return sort_clip_paths(list(final_dir.glob("clip_*_sub.mp4")))
    clips = sort_clip_paths(list(final_dir.glob("clip_*.mp4")))
    return [p for p in clips if not p.name.endswith("_sub.mp4")]
