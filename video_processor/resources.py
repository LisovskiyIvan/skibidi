"""Resource path helpers that work in development and in PyInstaller bundles."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _user_config_dir() -> Path:
    """Return the per-user config directory for OAuth and other secrets.

    Uses ``%APPDATA%/video_processor`` on Windows and ``~/.config/video_processor``
    elsewhere. The getter is intentionally side-effect free; callers that write
    resources are responsible for creating the directory.
    """
    base = Path(os.environ.get("APPDATA", os.path.expanduser("~/.config")))
    return base / "video_processor"


def _is_bundled() -> bool:
    return hasattr(sys, "_MEIPASS")


def _bundle_root() -> Path:
    # ``sys._MEIPASS`` is injected by PyInstaller at runtime.
    return Path(sys._MEIPASS)  # type: ignore[attr-defined]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_ffmpeg_path() -> Path | str:
    if _is_bundled():
        return _bundle_root() / "ffmpeg.exe"
    return "ffmpeg"


def get_ffprobe_path() -> Path | str:
    if _is_bundled():
        return _bundle_root() / "ffprobe.exe"
    return "ffprobe"


def get_default_model_dir() -> Path:
    """Return the Vosk model path without depending on the current directory.

    Resolution order is: ``VIDEO_PROCESSOR_MODEL_DIR`` override, bundled
    resource directory, then the source/install root.
    """
    override = os.environ.get("VIDEO_PROCESSOR_MODEL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if _is_bundled():
        return _bundle_root() / "vosk-model-small-ru-0.22"
    return _repo_root() / "vosk-model-small-ru-0.22"


def get_default_font_dir() -> Path:
    if _is_bundled():
        return _bundle_root() / "assets" / "oswald" / "static"
    return _repo_root() / "assets" / "oswald" / "static"


def get_default_font_path() -> Path:
    return get_default_font_dir() / "Oswald-Bold.ttf"


def get_default_font_name() -> str:
    # The Oswald family is installed; the style file handles bold.
    if get_default_font_path().exists():
        return "Oswald"
    return "Arial"


def get_default_credentials_path() -> Path:
    """Path to the OAuth 2.0 Desktop client secret file."""
    return _user_config_dir() / "client_secret.json"


def get_default_token_path() -> Path:
    """Path to the cached OAuth token file."""
    return _user_config_dir() / "token.json"


def get_default_upload_ledger_path() -> Path:
    """Path to the optional ledger of completed YouTube uploads."""
    return _user_config_dir() / "upload-ledger.json"
