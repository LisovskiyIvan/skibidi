"""YouTube upload configuration dataclass.

Kept separate from :class:`PipelineConfig` because upload is an optional,
independent concern: it needs OAuth secrets and video metadata rather than
Vosk/ffmpeg settings, and it may be invoked on an existing file without the
full transcription pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .resources import get_default_credentials_path, get_default_token_path


@dataclass
class YouTubeUploadConfig:
    """Configuration for uploading one or more videos to YouTube."""

    # Files to upload. If empty, the orchestrator raises :class:`PipelineError`.
    video_paths: list[Path] = field(default_factory=list)

    credentials_path: Path = field(default_factory=get_default_credentials_path)
    token_path: Path = field(default_factory=get_default_token_path)

    # Title is a template; ``{name}`` becomes the file stem, ``{idx}`` the
    # one-based index, ``{total}`` the total count, and zero-padded variants
    # like ``{idx:02d}`` are also supported.
    title: str = "{name}"
    description: str = ""
    # Stored as a list; ``as_dict`` serializes it as a comma-separated string
    # for human-readable config dumps.
    tags: list[str] = field(default_factory=list)
    # YouTube category id. "22" is "People & Blogs".
    category_id: str = "22"
    privacy_status: str = "private"
    notify_subscribers: bool = False

    chunksize: int = 10 * 1024 * 1024  # 10 MB resumable chunks

    scopes: list[str] = field(
        default_factory=lambda: ["https://www.googleapis.com/auth/youtube.upload"]
    )

    def as_dict(self) -> dict[str, Any]:
        """Serialize config to a JSON-safe dictionary."""
        return {
            "video_paths": [str(p) for p in self.video_paths],
            "credentials_path": str(self.credentials_path),
            "token_path": str(self.token_path),
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "category_id": self.category_id,
            "privacy_status": self.privacy_status,
            "notify_subscribers": self.notify_subscribers,
            "chunksize": self.chunksize,
            "scopes": self.scopes,
        }
