"""Tests for YouTube download helpers and orchestration."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from video_processor.progress import Step
from video_processor.youtube_download import (
    YouTubeDownloadError,
    _download_single,
    _make_progress_hook,
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
        d = asdict(cfg)
        assert d["urls"] == ["https://youtu.be/abc"]
        assert d["output_dir"] == Path("downloads")
        assert d["format"] == "best"
        assert d["outtmpl"] == "%(title)s.%(ext)s"
        assert d["restrict_filenames"] is False

    def test_default_template_contains_video_id(self) -> None:
        assert "%(id)s" in YouTubeDownloadConfig().outtmpl


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

        monkeypatch.setattr("video_processor.youtube_download._ensure_deps", lambda: None)
        monkeypatch.setattr("video_processor.youtube_download._download_single", fake_download)

        events: list[tuple[Step, int, int, str]] = []

        def progress(step: Step, current: int, total: int, message: str) -> None:
            events.append((step, current, total, message))

        result = download_from_youtube(cfg, progress)

        assert downloaded == urls
        assert result == fake_paths
        assert any(step is Step.DOWNLOAD for step, _, _, _ in events)
        assert events[-1][0] is Step.DONE


def test_unknown_size_progress_is_time_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([0.0, 0.2, 1.2])
    monkeypatch.setattr("video_processor.youtube_download.monotonic", lambda: next(times))
    events: list[str] = []
    hook = _make_progress_hook(
        lambda _step, _current, _total, message: events.append(message),
        0,
        1,
        "url",
        interval_seconds=1.0,
    )

    for downloaded in (1, 2, 3):
        hook({"status": "downloading", "downloaded_bytes": downloaded})

    assert events == ["downloading url 1 bytes", "downloading url 3 bytes"]


def test_download_uses_bundled_ffmpeg_and_returns_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_options: dict[str, Any] = {}
    final_path = tmp_path / "final.mp4"

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            captured_options.update(options)

        def __enter__(self) -> FakeYoutubeDL:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, download: bool) -> dict[str, Any]:
            final_path.write_bytes(b"video")
            for hook in captured_options["postprocessor_hooks"]:
                hook(
                    {
                        "status": "finished",
                        "info_dict": {"filepath": str(final_path)},
                    }
                )
            return {"id": "abc"}

        def prepare_filename(self, info: dict[str, Any]) -> str:
            return str(tmp_path / "before-merge.webm")

    monkeypatch.setattr("video_processor.youtube_download._ensure_deps", lambda: None)
    monkeypatch.setattr("video_processor.youtube_download.YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr("video_processor.youtube_download.DownloadError", RuntimeError)
    monkeypatch.setattr(
        "video_processor.youtube_download.get_ffmpeg_path",
        lambda: tmp_path / "ffmpeg",
    )

    result = _download_single(
        YouTubeDownloadConfig(urls=["url"], output_dir=tmp_path),
        "url",
        lambda *_args: None,
        0,
        1,
    )

    assert result == final_path
    assert captured_options["ffmpeg_location"] == str(tmp_path / "ffmpeg")
