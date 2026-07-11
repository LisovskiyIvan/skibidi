"""Tests for YouTube download helpers and orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from video_processor.progress import Step
from video_processor.youtube_download import (
    YouTubeDownloadError,
    download_from_youtube,
)
from video_processor.youtube_download_config import YouTubeDownloadConfig


class TestYouTubeDownloadConfig:
    def test_as_dict_round_trip(self) -> None:
        cfg = YouTubeDownloadConfig(
            urls=["https://youtu.be/abc"],
            output_dir=Path("downloads"),
            format="best",
            outtmpl="%(title)s.%(ext)s",
            restrict_filenames=False,
        )
        d = cfg.as_dict()
        assert d["urls"] == ["https://youtu.be/abc"]
        assert d["output_dir"] == "downloads"
        assert d["format"] == "best"
        assert d["outtmpl"] == "%(title)s.%(ext)s"
        assert d["restrict_filenames"] is False


class TestDownloadFromYouTubeValidation:
    def test_missing_urls_raises(self) -> None:
        cfg = YouTubeDownloadConfig(urls=[])
        with pytest.raises(YouTubeDownloadError, match="No URLs configured"):
            download_from_youtube(cfg)


class TestDownloadOrchestration:
    def test_downloads_all_urls_and_reports_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        urls = ["https://youtu.be/abc", "https://youtu.be/def"]
        cfg = YouTubeDownloadConfig(
            urls=urls,
            output_dir=tmp_path,
        )

        downloaded: list[str] = []
        fake_paths = [tmp_path / "abc.mp4", tmp_path / "def.mp4"]

        def fake_download(
            c: YouTubeDownloadConfig,
            url: str,
            progress: Any,
            idx: int,
            total: int,
        ) -> Path:
            assert c is cfg
            downloaded.append(url)
            progress(Step.DOWNLOAD, idx, total, f"mocked {url}")
            return fake_paths[idx]

        monkeypatch.setattr(
            "video_processor.youtube_download._ensure_deps", lambda: None
        )
        monkeypatch.setattr(
            "video_processor.youtube_download._download_single", fake_download
        )

        events: list[tuple[Step, int, int, str]] = []

        def progress(step: Step, current: int, total: int, message: str) -> None:
            events.append((step, current, total, message))

        result = download_from_youtube(cfg, progress)

        assert downloaded == urls
        assert result == fake_paths
        assert any(step is Step.DOWNLOAD for step, _, _, _ in events)
        assert events[-1][0] is Step.DONE
