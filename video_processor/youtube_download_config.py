"""YouTube download configuration dataclass.

Kept separate from :class:`PipelineConfig` because downloading is an optional,
independent concern: it needs a list of URLs and yt-dlp options rather than
Vosk/ffmpeg settings, and it may be invoked without running the full
transcription pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event


@dataclass
class YouTubeDownloadConfig:
    """Configuration for downloading one or more videos from YouTube."""

    # URLs to download. If empty, the orchestrator raises :class:`PipelineError`.
    urls: list[str] = field(default_factory=list)

    # Directory where downloaded files are saved.
    output_dir: Path = Path("downloads")

    # yt-dlp format selector. Default prefers mp4 because the rest of the
    # pipeline (segmentation, upload glob) expects ``.mp4`` files.
    format: str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    # yt-dlp output template. Title is truncated to 100 characters to avoid
    # exceeding filesystem path limits on Windows.
    outtmpl: str = "%(title).100s [%(id)s].%(ext)s"

    # Replace special characters in filenames with ASCII-safe equivalents.
    restrict_filenames: bool = True

    # Minimum interval for byte-only progress updates when size is unknown.
    progress_interval_seconds: float = 1.0
    cancel_event: Event | None = field(default=None, repr=False, compare=False)
