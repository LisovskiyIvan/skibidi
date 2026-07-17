"""Tests for YouTube download CLI wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from video_processor.cli import run_cli, youtube_download_config_from_args
from video_processor.youtube_download_config import YouTubeDownloadConfig


class TestYouTubeDownloadConfigFromArgs:
    def test_defaults(self) -> None:
        from argparse import Namespace

        args = Namespace(
            download=["https://youtu.be/abc"],
            output=Path("out"),
            dl_format=None,
            dl_template=None,
        )
        cfg = youtube_download_config_from_args(args)
        assert cfg.urls == ["https://youtu.be/abc"]
        assert cfg.output_dir == Path("out")
        assert cfg.format == YouTubeDownloadConfig().format

    def test_overrides(self) -> None:
        from argparse import Namespace

        args = Namespace(
            download=["https://youtu.be/abc"],
            output=Path("out"),
            dl_format="bestvideo+bestaudio",
            dl_template="test.%(ext)s",
        )
        cfg = youtube_download_config_from_args(args)
        assert cfg.format == "bestvideo+bestaudio"
        assert cfg.outtmpl == "test.%(ext)s"


class TestDownloadOnlyCli:
    def test_downloads_single_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[YouTubeDownloadConfig] = []

        def fake_download(config: YouTubeDownloadConfig, progress: Any = None) -> list[Path]:
            captured.append(config)
            return [tmp_path / "video.mp4"]

        monkeypatch.setattr("video_processor.cli.download_from_youtube", fake_download)

        returncode = run_cli(
            [
                "--download",
                "https://youtu.be/abc",
                "-o",
                str(tmp_path),
            ]
        )

        assert returncode == 0
        assert len(captured) == 1
        cfg = captured[0]
        assert cfg.urls == ["https://youtu.be/abc"]
        assert cfg.output_dir == tmp_path

    def test_downloads_multiple_urls(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[YouTubeDownloadConfig] = []

        def fake_download(config: YouTubeDownloadConfig, progress: Any = None) -> list[Path]:
            captured.append(config)
            return [tmp_path / "a.mp4", tmp_path / "b.mp4"]

        monkeypatch.setattr("video_processor.cli.download_from_youtube", fake_download)

        returncode = run_cli(
            [
                "--download",
                "https://youtu.be/abc",
                "https://youtu.be/def",
                "-o",
                str(tmp_path),
            ]
        )

        assert returncode == 0
        assert len(captured) == 1
        assert captured[0].urls == ["https://youtu.be/abc", "https://youtu.be/def"]

    def test_download_rejects_input(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            run_cli(["--download", "https://youtu.be/abc", "-i", str(tmp_path / "x.mp4")])
        assert exc_info.value.code == 2

    def test_download_rejects_upload_only(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            run_cli(
                [
                    "--download",
                    "https://youtu.be/abc",
                    "--upload-only",
                    str(tmp_path),
                ]
            )
        assert exc_info.value.code == 2

    def test_download_rejects_upload_flag(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            run_cli(["--download", "https://youtu.be/abc", "--upload"])
        assert exc_info.value.code == 2
