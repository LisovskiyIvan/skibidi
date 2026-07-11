"""Load environment variables from a local ``.env`` file.

A tiny dependency-free ``.env`` reader so secrets like ``HF_TOKEN`` can live in
``.env`` instead of the shell environment. It is invoked once at program start
(see :mod:`video_processor.__main__`) before any optional dependency that needs
the token (e.g. faster-whisper talking to the HuggingFace Hub) is initialised.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidate_env_paths() -> list[Path]:
    """Places to look for a ``.env`` file, in priority order."""
    paths: list[Path] = [Path.cwd() / ".env"]
    if hasattr(sys, "_MEIPASS"):  # PyInstaller bundle
        paths.append(Path(sys._MEIPASS) / ".env")
    else:
        # Repo root: this file lives at <root>/video_processor/env_loader.py
        paths.append(Path(__file__).resolve().parent.parent / ".env")
    return paths


def load_env_file() -> Path | None:
    """Populate ``os.environ`` from the first ``.env`` file found.

    Existing environment variables are NOT overridden, matching standard
    ``dotenv`` behaviour: a value already present in the real environment wins.
    Returns the path that was loaded, or ``None`` if no ``.env`` was found.
    """
    for env_path in _candidate_env_paths():
        if env_path.is_file():
            _apply_env_file(env_path)
            return env_path
    return None


def _apply_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip a single pair of matching surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
