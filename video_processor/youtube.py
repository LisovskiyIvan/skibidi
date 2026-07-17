"""YouTube Data API v3 upload helper.

This module wraps the Google API client with the same patterns used by the
rest of the core: a single typed config object, the shared ``ProgressCallback``
protocol, and ``PipelineError`` for expected failures.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from importlib.util import find_spec
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


YOUTUBE_AVAILABLE = (
    find_spec("googleapiclient") is not None and find_spec("google_auth_oauthlib") is not None
)

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
    global Credentials, InstalledAppFlow, MediaFileUpload
    global MediaUploadProgress, Request, YOUTUBE_AVAILABLE, build

    if Credentials is None:
        try:
            from google.auth.transport.requests import Request as request_type
            from google.oauth2.credentials import Credentials as credentials_type
            from google_auth_oauthlib.flow import InstalledAppFlow as flow_type
            from googleapiclient.discovery import build as build_function
            from googleapiclient.http import MediaFileUpload as media_file_upload_type
            from googleapiclient.http import MediaUploadProgress as media_progress_type
        except ImportError:
            YOUTUBE_AVAILABLE = False
        else:
            build = build_function
            MediaFileUpload = media_file_upload_type
            MediaUploadProgress = media_progress_type
            InstalledAppFlow = flow_type
            Request = request_type
            Credentials = credentials_type
            YOUTUBE_AVAILABLE = True
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


def validate_title_template(template: str) -> None:
    """Validate a title template without requiring an upload or OAuth."""
    try:
        title = _resolve_title(template, Path("video.mp4"), 1, 1)
    except (AttributeError, IndexError, KeyError, ValueError) as exc:
        raise YouTubeUploadError(f"Invalid title template {template!r}: {exc}") from exc
    if not title.strip():
        raise YouTubeUploadError("YouTube title template must not produce an empty title")


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


def _atomic_write_private(path: Path, contents: str, label: str) -> None:
    """Atomically replace a private file without following a destination symlink."""
    if path.is_symlink():
        raise YouTubeUploadError(f"Refusing to write {label} through symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1
    temporary = ""
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            fd = -1
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
        if path.is_symlink():
            raise YouTubeUploadError(f"Refusing to write {label} through symlink: {path}")
        os.replace(temporary, path)
        temporary = ""
        if os.name == "posix":
            path.chmod(0o600)
    except YouTubeUploadError:
        raise
    except OSError as exc:
        raise YouTubeUploadError(f"Failed to save {label}: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def _preflight(config: YouTubeUploadConfig) -> list[str]:
    """Validate every upload input and return its stable ledger key."""
    if not config.video_paths:
        raise YouTubeUploadError("No video files configured for upload")
    if config.privacy_status not in VALID_PRIVACY_STATUSES:
        raise YouTubeUploadError(
            f"Invalid privacy status {config.privacy_status!r}. "
            f"Choose one of: {', '.join(sorted(VALID_PRIVACY_STATUSES))}"
        )
    validate_title_template(config.title)
    if (
        config.chunksize <= 0
        or config.max_retries < 0
        or config.retry_backoff_seconds < 0
        or config.max_retry_backoff_seconds < 0
    ):
        raise YouTubeUploadError(
            "Upload chunk size must be positive and retry values must not be negative"
        )

    upload_scope = str(config.token_path.expanduser().resolve())
    if config.token_path.is_file() and not config.token_path.is_symlink():
        try:
            token_data = json.loads(config.token_path.read_text(encoding="utf-8"))
            if isinstance(token_data, dict):
                stable_identity = {
                    "client_id": token_data.get("client_id"),
                    "refresh_token": token_data.get("refresh_token"),
                }
                if any(stable_identity.values()):
                    upload_scope = hashlib.sha256(
                        json.dumps(stable_identity, sort_keys=True).encode()
                    ).hexdigest()
        except (json.JSONDecodeError, OSError):
            pass
    total = len(config.video_paths)
    keys: list[str] = []
    for idx, video_path in enumerate(config.video_paths, start=1):
        if not video_path.is_file():
            raise YouTubeUploadError(f"Video file not found: {video_path}")
        try:
            title = _resolve_title(config.title, video_path, idx, total)
        except (AttributeError, IndexError, KeyError, ValueError) as exc:
            raise YouTubeUploadError(
                f"Invalid title template for {video_path.name}: {exc}"
            ) from exc
        if not title.strip():
            raise YouTubeUploadError(f"YouTube title is empty for {video_path.name}")
        try:
            stat = video_path.stat()
        except OSError as exc:
            raise YouTubeUploadError(f"Cannot read video file {video_path}: {exc}") from exc
        identity = json.dumps(
            {
                "path": str(video_path.resolve()),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "title": title,
                "description": config.description,
                "tags": config.tags,
                "category_id": config.category_id,
                "privacy": config.privacy_status,
                "notify_subscribers": config.notify_subscribers,
                "upload_scope": upload_scope,
            },
            sort_keys=True,
        )
        keys.append(hashlib.sha256(identity.encode()).hexdigest())
    return keys


def _load_ledger(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    if path.is_symlink():
        raise YouTubeUploadError(f"Refusing to read upload ledger through symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(video_id, str) for key, video_id in value.items()
        ):
            raise ValueError("expected an object mapping upload keys to video ids")
        return value
    except (OSError, UnicodeError, ValueError) as exc:
        raise YouTubeUploadError(f"Invalid upload ledger: {exc}") from exc


def _check_cancelled(config: YouTubeUploadConfig) -> None:
    if config.cancel_event is not None and config.cancel_event.is_set():
        raise YouTubeUploadError("YouTube upload cancelled")


def _authenticate(config: YouTubeUploadConfig) -> Any:
    """Return an authenticated YouTube API service object.

    Loads cached credentials from ``config.token_path`` if available; refreshes
    an expired access token automatically. If no valid credentials are found,
    launches the local OAuth flow using ``config.credentials_path`` and saves the
    resulting token for future automatic runs.
    """
    _ensure_deps()
    assert Credentials is not None
    assert build is not None

    creds: Any = None
    if config.token_path.is_symlink():
        raise YouTubeUploadError(
            f"Refusing to read OAuth token through symlink: {config.token_path}"
        )
    if config.token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(config.token_path), config.scopes)
        except (OSError, ValueError) as exc:
            raise YouTubeUploadError(f"Invalid token file: {exc}") from exc

    if creds and creds.valid:
        return build(API_SERVICE_NAME, API_VERSION, credentials=creds)

    if creds and creds.expired and creds.refresh_token:
        assert Request is not None
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001
            raise YouTubeUploadError(f"Failed to refresh access token: {exc}") from exc
    else:
        assert InstalledAppFlow is not None
        if not config.credentials_path.is_file():
            raise YouTubeUploadError(
                f"Missing OAuth credentials file: {config.credentials_path}\n"
                "Download it from Google Cloud Console (OAuth 2.0 Desktop client) "
                "and place it at the path above."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.credentials_path), config.scopes
        )
        creds = flow.run_local_server(port=0)

    _atomic_write_private(config.token_path, creds.to_json(), "OAuth token")

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
    retry_count = 0
    while response is None:
        _check_cancelled(config)
        try:
            status, response = request.next_chunk()
        except Exception as exc:  # noqa: BLE001
            response_status = getattr(getattr(exc, "resp", None), "status", None)
            content = getattr(exc, "content", b"")
            if isinstance(content, str):
                content = content.encode()
            elif not isinstance(content, bytes):
                content = b""
            rate_limited = response_status == 403 and any(
                reason in content for reason in (b"rateLimitExceeded", b"userRateLimitExceeded")
            )
            retryable = (
                response_status in {429, 500, 502, 503, 504}
                or rate_limited
                or isinstance(exc, (ConnectionError, OSError, TimeoutError))
            )
            if not retryable or retry_count >= config.max_retries:
                raise YouTubeUploadError(f"Upload failed for {video_path.name}: {exc}") from exc
            delay = min(
                config.retry_backoff_seconds * (2**retry_count),
                config.max_retry_backoff_seconds,
            )
            retry_count += 1
            progress(
                Step.UPLOAD,
                idx - 1,
                total,
                f"transient upload error; retry {retry_count}/{config.max_retries} in {delay:g}s",
            )
            if config.cancel_event is not None:
                if config.cancel_event.wait(delay):
                    _check_cancelled(config)
            else:
                time.sleep(delay)
            continue
        retry_count = 0
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
    ledger_keys = _preflight(config)
    ledger = _load_ledger(config.ledger_path)
    total = len(config.video_paths)
    video_ids: list[str] = []
    service: Any = None
    if any(key not in ledger for key in ledger_keys) and not config.token_path.is_file():
        service = _authenticate(config)
        # A first OAuth flow creates the token; scope ledger keys to that account.
        ledger_keys = _preflight(config)
        ledger = _load_ledger(config.ledger_path)
    for idx, (video_path, ledger_key) in enumerate(zip(config.video_paths, ledger_keys), start=1):
        _check_cancelled(config)
        video_id = ledger.get(ledger_key)
        if video_id is not None:
            progress(
                Step.UPLOAD,
                idx - 1,
                total,
                f"skip previously uploaded {video_path.name} -> https://youtu.be/{video_id}",
            )
        else:
            if service is None:
                service = _authenticate(config)
            video_id = _upload_single_video(config, service, video_path, idx, total, progress)
            if config.ledger_path is not None:
                ledger[ledger_key] = video_id
                _atomic_write_private(
                    config.ledger_path,
                    json.dumps(ledger, indent=2, sort_keys=True) + "\n",
                    "upload ledger",
                )
        video_ids.append(video_id)

    progress(
        Step.DONE,
        total,
        total,
        f"uploaded {len(video_ids)} video(s); ids={video_ids}",
    )
    return video_ids
