"""YouTube Data API v3 upload helper.

This module wraps the Google API client with the same patterns used by the
rest of the core: a single typed config object, the shared ``ProgressCallback``
protocol, and ``PipelineError`` for expected failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._optional_deps import ensure_optional_dep
from .errors import PipelineError
from .progress import ProgressCallback, Step, noop_progress
from .youtube_config import YouTubeUploadConfig


class _GoogleApi:
    """Runtime holder for Google API symbols (may be absent)."""

    build: Any = None
    MediaFileUpload: Any = None
    MediaUploadProgress: Any = None
    InstalledAppFlow: Any = None
    Request: Any = None
    Credentials: Any = None


YOUTUBE_AVAILABLE = False

try:
    from google.auth.transport.requests import Request as _Request
    from google.oauth2.credentials import Credentials as _Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow as _InstalledAppFlow
    from googleapiclient.discovery import build as _build
    from googleapiclient.http import MediaFileUpload as _MediaFileUpload
    from googleapiclient.http import MediaUploadProgress as _MediaUploadProgress

    _GoogleApi.build = _build
    _GoogleApi.MediaFileUpload = _MediaFileUpload
    _GoogleApi.MediaUploadProgress = _MediaUploadProgress
    _GoogleApi.InstalledAppFlow = _InstalledAppFlow
    _GoogleApi.Request = _Request
    _GoogleApi.Credentials = _Credentials
    YOUTUBE_AVAILABLE = True
except ImportError:
    pass

build = _GoogleApi.build
MediaFileUpload = _GoogleApi.MediaFileUpload
MediaUploadProgress = _GoogleApi.MediaUploadProgress
InstalledAppFlow = _GoogleApi.InstalledAppFlow
Request = _GoogleApi.Request
Credentials = _GoogleApi.Credentials

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
VALID_PRIVACY_STATUSES = {"private", "unlisted", "public"}


class YouTubeUploadError(PipelineError):
    """Raised when a YouTube-specific operation fails."""

    pass


def _ensure_deps() -> None:
    ensure_optional_dep(
        YOUTUBE_AVAILABLE,
        "YouTube upload dependencies",
        "pip install -e '.[youtube]'",
    )


def _resolve_title(template: str, video_path: Path, idx: int, total: int) -> str:
    """Fill a title template with per-video metadata.

    Supported placeholders: ``{name}``, ``{idx}``, ``{total}``, and any
    zero-padded variants such as ``{idx:02d}``.
    """
    mapping: dict[str, Any] = {
        "name": video_path.stem,
        "idx": idx,
        "total": total,
    }
    return template.format(**mapping)


def _build_video_body(
    config: YouTubeUploadConfig,
    video_path: Path,
    idx: int,
    total: int,
) -> dict[str, Any]:
    """Build the request body for the YouTube videos.insert endpoint."""
    snippet: dict[str, Any] = {
        "title": _resolve_title(config.title, video_path, idx, total)[:100],
        "description": config.description,
        "categoryId": config.category_id,
    }
    if config.tags:
        snippet["tags"] = config.tags
    body: dict[str, Any] = {
        "snippet": snippet,
        "status": {
            "privacyStatus": config.privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    return body


def _authenticate(config: YouTubeUploadConfig) -> Any:
    """Return an authenticated YouTube API service object.

    Loads cached credentials from ``config.token_path`` if available; refreshes
    an expired access token automatically. If no valid credentials are found,
    launches the local OAuth flow using ``config.credentials_path`` and saves the
    resulting token for future automatic runs.
    """
    _ensure_deps()
    assert Credentials is not None
    assert InstalledAppFlow is not None
    assert Request is not None

    if not config.credentials_path.exists():
        raise YouTubeUploadError(
            f"Missing OAuth credentials file: {config.credentials_path}\n"
            "Download it from Google Cloud Console (OAuth 2.0 Desktop client) "
            "and place it at the path above."
        )

    creds: Any = None
    if config.token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(
                str(config.token_path), config.scopes
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise YouTubeUploadError(f"Invalid token file: {exc}") from exc

    if creds and creds.valid:
        return build(API_SERVICE_NAME, API_VERSION, credentials=creds)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001
            raise YouTubeUploadError(f"Failed to refresh access token: {exc}") from exc
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.credentials_path), config.scopes
        )
        creds = flow.run_local_server(port=0)

    config.token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        config.token_path.write_text(creds.to_json(), encoding="utf-8")
    except OSError as exc:
        raise YouTubeUploadError(f"Failed to save token: {exc}") from exc

    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)


def _upload_single_video(
    config: YouTubeUploadConfig,
    service: Any,
    video_path: Path,
    idx: int,
    total: int,
    progress: ProgressCallback,
) -> str:
    """Upload one video file and return its YouTube video id.

    Uses a resumable upload so that the progress callback receives percent
    updates during the transfer (``next_chunk()`` loop pattern).
    """
    _ensure_deps()
    assert MediaFileUpload is not None
    assert MediaUploadProgress is not None

    if not video_path.exists():
        raise YouTubeUploadError(f"Video file not found: {video_path}")

    body = _build_video_body(config, video_path, idx, total)
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/*",
        chunksize=config.chunksize,
        resumable=True,
    )

    request = service.videos().insert(
        part=",".join(["snippet", "status"]),
        body=body,
        media_body=media,
        notifySubscribers=config.notify_subscribers,
    )

    progress(
        Step.UPLOAD,
        idx - 1,
        total,
        f"starting upload of {video_path.name}",
    )

    response: Any = None
    while response is None:
        try:
            status, response = request.next_chunk()
        except Exception as exc:  # noqa: BLE001
            raise YouTubeUploadError(
                f"Upload failed for {video_path.name}: {exc}"
            ) from exc
        if status and hasattr(status, "progress"):
            pct = int(status.progress() * 100)
            progress(
                Step.UPLOAD,
                idx - 1,
                total,
                f"uploading {video_path.name} {pct}%",
            )

    video_id = response.get("id") if isinstance(response, dict) else None
    if not video_id:
        raise YouTubeUploadError(
            f"Upload succeeded but no video id was returned for {video_path.name}"
        )

    progress(
        Step.UPLOAD,
        idx - 1,
        total,
        f"finished {video_path.name} -> https://youtu.be/{video_id}",
    )
    return str(video_id)


def upload_to_youtube(
    config: YouTubeUploadConfig,
    progress: ProgressCallback = noop_progress,
) -> list[str]:
    """Upload all configured videos and return their YouTube video ids.

    This is the top-level entry point intended to be called from the CLI, GUI,
    or external scripts. It handles authentication, validates input, and reports
    progress via the same protocol used by the transcription pipeline.
    """
    if not config.video_paths:
        raise YouTubeUploadError("No video files configured for upload")

    if config.privacy_status not in VALID_PRIVACY_STATUSES:
        raise YouTubeUploadError(
            f"Invalid privacy status {config.privacy_status!r}. "
            f"Choose one of: {', '.join(sorted(VALID_PRIVACY_STATUSES))}"
        )

    service = _authenticate(config)
    total = len(config.video_paths)

    video_ids: list[str] = []
    for idx, video_path in enumerate(config.video_paths, start=1):
        video_id = _upload_single_video(
            config, service, video_path, idx, total, progress
        )
        video_ids.append(video_id)

    progress(
        Step.DONE,
        total,
        total,
        f"uploaded {len(video_ids)} video(s); ids={video_ids}",
    )
    return video_ids
