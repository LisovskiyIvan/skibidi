"""Resource path helpers that work in development and in PyInstaller bundles."""

from __future__ import annotations

import sys
from pathlib import Path


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
    if _is_bundled():
        return _bundle_root() / "vosk-model-small-ru-0.22"
    return Path("vosk-model-small-ru-0.22")


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
