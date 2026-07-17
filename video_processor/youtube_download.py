"""YouTube video download helper using yt-dlp.

This module wraps yt-dlp with the same patterns used by the rest of the core:
a single typed config object, the shared ``ProgressCallback`` protocol, and
``PipelineError`` for expected failures.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Any

from ._optional_deps import ensure_optional_dep
from .errors import PipelineError
from .progress import ProgressCallback, Step, noop_progress
from .resources import get_ffmpeg_path
from .youtube_download_config import YouTubeDownloadConfig


class _YtDlp:
    """Runtime holder for yt-dlp symbols (may be absent)."""

    YoutubeDL: Any = None
    DownloadError: Any = None


YOUTUBE_DOWNLOAD_AVAILABLE = find_spec("yt_dlp") is not None

YoutubeDL = _YtDlp.YoutubeDL
DownloadError = _YtDlp.DownloadError


class YouTubeDownloadError(PipelineError):
    """Raised when a YouTube-specific download operation fails."""

    pass


def _ensure_deps() -> None:
    global DownloadError, YOUTUBE_DOWNLOAD_AVAILABLE, YoutubeDL

    if YoutubeDL is None:
        try:
            from yt_dlp import DownloadError as download_error_type
            from yt_dlp import YoutubeDL as youtube_dl_type
        except ImportError:
            YOUTUBE_DOWNLOAD_AVAILABLE = False
        else:
            YoutubeDL = youtube_dl_type
            DownloadError = download_error_type
            YOUTUBE_DOWNLOAD_AVAILABLE = True
    ensure_optional_dep(
        YOUTUBE_DOWNLOAD_AVAILABLE,
        "YouTube download dependencies",
        "pip install -e '.[download]'",
    )


def _make_progress_hook(
    progress: ProgressCallback,
    idx: int,
    total: int,
    url: str,
    interval_seconds: float = 1.0,
    cancel_event: Event | None = None,
) -> Callable[[dict[str, Any]], None]:
    """Return a yt-dlp progress hook that reports throttled progress.

    Progress is bucketed to 5% steps so the CLI output stays readable while the
    GUI still gets smooth-enough updates. When the total size is unknown, only
    the downloaded byte count is reported.
    """
    state: dict[str, int | float] = {"bucket": -1, "last_report": float("-inf")}

    def hook(d: dict[str, Any]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise YouTubeDownloadError("YouTube download cancelled")
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
                    now = monotonic()
                    if now - state["last_report"] < interval_seconds:
                        return
                    state["last_report"] = now
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


def _capture_postprocessed_path(paths: list[Path]) -> Callable[[dict[str, Any]], None]:
    """Capture yt-dlp's path after post-processing/moving when available."""

    def hook(data: dict[str, Any]) -> None:
        if data.get("status") != "finished":
            return
        info = data.get("info_dict")
        if isinstance(info, dict) and isinstance(info.get("filepath"), str):
            paths.append(Path(info["filepath"]))
        elif isinstance(data.get("filepath"), str):
            paths.append(Path(data["filepath"]))

    return hook


def _verified_final_path(
    info: dict[str, Any],
    prepared_filename: str,
    postprocessed_paths: list[Path],
    output_dir: Path,
) -> Path:
    """Resolve and verify the final file produced by yt-dlp."""
    candidates = list(reversed(postprocessed_paths))
    filepath = info.get("filepath")
    if isinstance(filepath, str):
        candidates.append(Path(filepath))
    original_filename = info.get("_filename")
    if isinstance(original_filename, str):
        candidates.append(Path(original_filename))
    requested = info.get("requested_downloads")
    if isinstance(requested, list):
        for item in reversed(requested):
            if isinstance(item, dict) and isinstance(item.get("filepath"), str):
                candidates.append(Path(item["filepath"]))
    files_to_move = info.get("__files_to_move")
    if isinstance(files_to_move, dict):
        candidates.extend(Path(path) for path in files_to_move.values() if isinstance(path, str))
    candidates.append(Path(prepared_filename))

    for candidate in candidates:
        expanded = candidate if candidate.is_absolute() else output_dir / candidate
        if candidate.is_file():
            return candidate
        if expanded.is_file():
            return expanded
    rendered = ", ".join(str(path) for path in candidates)
    raise YouTubeDownloadError(
        f"yt-dlp completed but the final downloaded file was not found: {rendered}"
    )


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
    postprocessed_paths: list[Path] = []

    ydl_opts: dict[str, Any] = {
        "format": config.format,
        "outtmpl": config.outtmpl,
        "paths": {"home": str(config.output_dir)},
        "restrict_filenames": config.restrict_filenames,
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "progress_hooks": [
            _make_progress_hook(
                progress,
                idx,
                total,
                url,
                config.progress_interval_seconds,
                config.cancel_event,
            )
        ],
        "postprocessor_hooks": [_capture_postprocessed_path(postprocessed_paths)],
    }
    ffmpeg_path = get_ffmpeg_path()
    if isinstance(ffmpeg_path, Path):
        ydl_opts["ffmpeg_location"] = str(ffmpeg_path)

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
            if config.cancel_event is not None and config.cancel_event.is_set():
                raise YouTubeDownloadError("YouTube download cancelled")
            filename = _verified_final_path(
                info,
                ydl.prepare_filename(info),
                postprocessed_paths,
                config.output_dir,
            )
    except YouTubeDownloadError:
        raise
    except DownloadError as exc:
        raise YouTubeDownloadError(f"Failed to download {url}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise YouTubeDownloadError(f"Failed to download {url}: {exc}") from exc

    return filename


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
    if config.progress_interval_seconds < 0:
        raise YouTubeDownloadError("Progress interval must not be negative")

    total = len(config.urls)
    downloaded_paths: list[Path] = []
    for idx, url in enumerate(config.urls, start=1):
        if config.cancel_event is not None and config.cancel_event.is_set():
            raise YouTubeDownloadError("YouTube download cancelled")
        video_path = _download_single(config, url, progress, idx - 1, total)
        downloaded_paths.append(video_path)

    progress(
        Step.DONE,
        total,
        total,
        f"downloaded {len(downloaded_paths)} video(s); paths={downloaded_paths}",
    )
    return downloaded_paths
