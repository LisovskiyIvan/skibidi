"""YouTube video download helper using yt-dlp.

This module wraps yt-dlp with the same patterns used by the rest of the core:
a single typed config object, the shared ``ProgressCallback`` protocol, and
``PipelineError`` for expected failures.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import PipelineError
from .progress import ProgressCallback, Step, noop_progress
from .youtube_download_config import YouTubeDownloadConfig


class _YtDlp:
    """Runtime holder for yt-dlp symbols (may be absent)."""

    YoutubeDL: Any = None
    DownloadError: Any = None


YOUTUBE_DOWNLOAD_AVAILABLE = False

try:
    from yt_dlp import DownloadError as _DownloadError
    from yt_dlp import YoutubeDL as _YoutubeDL

    _YtDlp.YoutubeDL = _YoutubeDL
    _YtDlp.DownloadError = _DownloadError
    YOUTUBE_DOWNLOAD_AVAILABLE = True
except ImportError:
    pass

YoutubeDL = _YtDlp.YoutubeDL
DownloadError = _YtDlp.DownloadError


class YouTubeDownloadError(PipelineError):
    """Raised when a YouTube-specific download operation fails."""

    pass


def _ensure_deps() -> None:
    if not YOUTUBE_DOWNLOAD_AVAILABLE:
        raise YouTubeDownloadError(
            "YouTube download dependencies are not installed. "
            "Install them with: pip install -e '.[download]'"
        )


def _make_progress_hook(
    progress: ProgressCallback,
    idx: int,
    total: int,
    url: str,
) -> Callable[[dict[str, Any]], None]:
    """Return a yt-dlp progress hook that reports throttled progress.

    Progress is bucketed to 5% steps so the CLI output stays readable while the
    GUI still gets smooth-enough updates. When the total size is unknown, only
    the downloaded byte count is reported.
    """
    state = {"bucket": -1}

    def hook(d: dict[str, Any]) -> None:
        status = d.get("status")
        if status == "downloading":
            downloaded = d.get("downloaded_bytes")
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate")
            if isinstance(downloaded, int) and downloaded >= 0:
                if total_bytes:
                    pct = min(downloaded / total_bytes * 100.0, 100.0)
                    bucket = int(pct) // 5 * 5
                    if bucket == state["bucket"]:
                        return
                    state["bucket"] = bucket
                    progress(
                        Step.DOWNLOAD,
                        idx,
                        total,
                        f"downloading {url} {pct:.0f}%",
                    )
                else:
                    progress(
                        Step.DOWNLOAD,
                        idx,
                        total,
                        f"downloading {url} {downloaded} bytes",
                    )
        elif status == "finished":
            filename = d.get("filename", url)
            progress(
                Step.DOWNLOAD,
                idx,
                total,
                f"finished {filename}",
            )

    return hook


def _download_single(
    config: YouTubeDownloadConfig,
    url: str,
    progress: ProgressCallback,
    idx: int,
    total: int,
) -> Path:
    """Download a single URL and return the path to the saved file."""
    _ensure_deps()
    assert YoutubeDL is not None
    assert DownloadError is not None

    config.output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts: dict[str, Any] = {
        "format": config.format,
        "outtmpl": config.outtmpl,
        "paths": {"home": str(config.output_dir)},
        "restrict_filenames": config.restrict_filenames,
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "progress_hooks": [_make_progress_hook(progress, idx, total, url)],
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            progress(
                Step.DOWNLOAD,
                idx,
                total,
                f"starting download {url}",
            )
            info = ydl.extract_info(url, download=True)
            if not info:
                raise YouTubeDownloadError(f"No video info returned for {url}")
            filename = ydl.prepare_filename(info)
    except DownloadError as exc:
        raise YouTubeDownloadError(f"Failed to download {url}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise YouTubeDownloadError(f"Failed to download {url}: {exc}") from exc

    return Path(filename)


def download_from_youtube(
    config: YouTubeDownloadConfig,
    progress: ProgressCallback = noop_progress,
) -> list[Path]:
    """Download all configured URLs and return paths to the saved files.

    This is the top-level entry point intended to be called from the CLI, GUI,
    or external scripts. It validates input, ensures yt-dlp is installed, and
    reports progress via the same protocol used by the transcription pipeline.
    """
    if not config.urls:
        raise YouTubeDownloadError("No URLs configured for download")

    total = len(config.urls)
    downloaded_paths: list[Path] = []
    for idx, url in enumerate(config.urls, start=1):
        video_path = _download_single(config, url, progress, idx - 1, total)
        downloaded_paths.append(video_path)

    progress(
        Step.DONE,
        total,
        total,
        f"downloaded {len(downloaded_paths)} video(s); "
        f"paths={downloaded_paths}",
    )
    return downloaded_paths
