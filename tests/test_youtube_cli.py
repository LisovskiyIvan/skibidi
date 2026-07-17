"""Tests for YouTube CLI wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from video_processor.cli import run_cli, youtube_config_from_args
from video_processor.youtube_config import YouTubeUploadConfig


def _args(**overrides: Any) -> Any:
    """Build a fake argparse Namespace with the upload defaults."""
    defaults: dict[str, Any] = {
        "yt_credentials": Path("client_secret.json"),
        "yt_token": Path("token.json"),
        "yt_title": "{name}",
        "yt_description": "",
        "yt_tags": None,
        "yt_privacy": "private",
        "yt_category": "22",
        "yt_notify": False,
    }
    defaults.update(overrides)
    from argparse import Namespace

    return Namespace(**defaults)


class TestYouTubeConfigFromArgs:
    def test_tags_split(self) -> None:
        args = _args(yt_tags="a, b, c")
        cfg = youtube_config_from_args(args, [Path("v.mp4")])
        assert cfg.tags == ["a", "b", "c"]

    def test_no_tags_empty(self) -> None:
        args = _args()
        cfg = youtube_config_from_args(args, [Path("v.mp4")])
        assert cfg.tags == []


class TestUploadOnlyCli:
    def test_uploads_single_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        captured: list[YouTubeUploadConfig] = []

        def fake_upload(config: YouTubeUploadConfig, progress: Any = None) -> list[str]:
            captured.append(config)
            return ["fakeid"]

        monkeypatch.setattr("video_processor.cli.upload_to_youtube", fake_upload)

        returncode = run_cli(
            [
                "--upload-only",
                str(video),
                "--yt-title",
                "My clip {idx:02d}",
                "--yt-description",
                "test",
                "--yt-tags",
                "shorts,video",
                "--yt-privacy",
                "public",
            ]
        )

        assert returncode == 0
        assert len(captured) == 1
        cfg = captured[0]
        assert cfg.video_paths == [video]
        assert cfg.title == "My clip {idx:02d}"
        assert cfg.description == "test"
        assert cfg.tags == ["shorts", "video"]
        assert cfg.privacy_status == "public"

    def test_uploads_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "a.mp4").write_bytes(b"\x00")
        (tmp_path / "b.mp4").write_bytes(b"\x00")
        (tmp_path / "note.txt").write_text("skip")

        captured: list[YouTubeUploadConfig] = []

        def fake_upload(config: YouTubeUploadConfig, progress: Any = None) -> list[str]:
            captured.append(config)
            return ["id"]

        monkeypatch.setattr("video_processor.cli.upload_to_youtube", fake_upload)

        returncode = run_cli(["--upload-only", str(tmp_path)])

        assert returncode == 0
        assert len(captured) == 1
        assert [p.name for p in captured[0].video_paths] == ["a.mp4", "b.mp4"]

    def test_uploads_directory_in_numeric_clip_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("clip_10.mp4", "clip_2.mp4", "clip_1.mp4"):
            (tmp_path / name).write_bytes(b"\x00")
        captured: list[YouTubeUploadConfig] = []

        def fake_upload(config: YouTubeUploadConfig, progress: Any = None) -> list[str]:
            captured.append(config)
            return ["id"]

        monkeypatch.setattr(
            "video_processor.cli.upload_to_youtube",
            fake_upload,
        )

        assert run_cli(["--upload-only", str(tmp_path)]) == 0
        assert [path.name for path in captured[0].video_paths] == [
            "clip_1.mp4",
            "clip_2.mp4",
            "clip_10.mp4",
        ]

    def test_no_mp4_files_error(self, tmp_path: Path) -> None:
        returncode = run_cli(["--upload-only", str(tmp_path)])
        assert returncode == 1

    def test_upload_only_rejects_input(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            run_cli(["--upload-only", str(tmp_path), "-i", str(tmp_path)])
        assert exc_info.value.code == 2

    def test_upload_only_rejects_pipeline_upload(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            run_cli(["--upload-only", str(tmp_path), "--upload"])
        assert exc_info.value.code == 2
