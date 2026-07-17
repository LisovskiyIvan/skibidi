"""Tests for YouTube upload helpers and orchestration."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from video_processor.progress import Step
from video_processor.youtube import YouTubeUploadError, _resolve_title, upload_to_youtube
from video_processor.youtube_config import YouTubeUploadConfig


class TestResolveTitle:
    def test_name_placeholder(self) -> None:
        path = Path("out/final/clip_00_sub.mp4")
        assert _resolve_title("{name}", path, 1, 1) == "clip_00_sub"

    def test_index_and_total(self) -> None:
        path = Path("video.mp4")
        assert _resolve_title("{idx} of {total}", path, 3, 5) == "3 of 5"

    def test_zero_padded_index(self) -> None:
        path = Path("video.mp4")
        assert _resolve_title("Clip {idx:02d}", path, 7, 10) == "Clip 07"


class TestYouTubeUploadConfig:
    def test_as_dict_round_trip(self) -> None:
        cfg = YouTubeUploadConfig(
            video_paths=[Path("a.mp4"), Path("b.mp4")],
            title="Test {idx}",
            description="desc",
            tags=["tag1", "tag2"],
            privacy_status="public",
        )
        d = asdict(cfg)
        assert d["video_paths"] == [Path("a.mp4"), Path("b.mp4")]
        assert d["title"] == "Test {idx}"
        assert d["description"] == "desc"
        assert d["tags"] == ["tag1", "tag2"]
        assert d["privacy_status"] == "public"
        assert d["category_id"] == "22"


class TestUploadToYouTubeValidation:
    def test_missing_video_paths_raises(self) -> None:
        cfg = YouTubeUploadConfig(video_paths=[])
        with pytest.raises(YouTubeUploadError, match="No video files configured"):
            upload_to_youtube(cfg)

    def test_invalid_privacy_raises(self) -> None:
        cfg = YouTubeUploadConfig(
            video_paths=[Path("v.mp4")], privacy_status="secret"
        )
        with pytest.raises(YouTubeUploadError, match="Invalid privacy status"):
            upload_to_youtube(cfg)

class TestUploadOrchestration:
    def test_uploads_all_paths_and_reports_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        videos = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        for v in videos:
            v.write_bytes(b"\x00")

        cfg = YouTubeUploadConfig(video_paths=videos)

        uploaded: list[Path] = []
        fake_ids = ["id1", "id2"]

        def fake_upload(
            c: YouTubeUploadConfig,
            service: Any,
            video_path: Path,
            idx: int,
            total: int,
            progress: Any,
        ) -> str:
            uploaded.append(video_path)
            progress(Step.UPLOAD, idx - 1, total, f"mocked {video_path.name}")
            return fake_ids[idx - 1]

        monkeypatch.setattr("video_processor.youtube._ensure_deps", lambda: None)
        monkeypatch.setattr("video_processor.youtube._authenticate", lambda c: object())
        monkeypatch.setattr("video_processor.youtube._upload_single_video", fake_upload)

        events: list[tuple[Step, int, int, str]] = []

        def progress(step: Step, current: int, total: int, message: str) -> None:
            events.append((step, current, total, message))

        result = upload_to_youtube(cfg, progress)

        assert uploaded == videos
        assert result == fake_ids
        assert any(step is Step.UPLOAD for step, _, _, _ in events)
        assert events[-1][0] is Step.DONE

    def test_missing_credentials_file_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = YouTubeUploadConfig(
            video_paths=[tmp_path / "v.mp4"],
            credentials_path=tmp_path / "missing.json",
        )
        (tmp_path / "v.mp4").write_bytes(b"\x00")
        monkeypatch.setattr(
            "video_processor.youtube._authenticate",
            lambda c: (_ for _ in ()).throw(
                YouTubeUploadError(f"Missing OAuth credentials: {c.credentials_path}")
            ),
        )
        with pytest.raises(YouTubeUploadError, match="Missing OAuth credentials"):
            upload_to_youtube(cfg)
