"""Tests for YouTube upload helpers and orchestration."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from video_processor.progress import Step
from video_processor.youtube import (
    YouTubeUploadError,
    _atomic_write_private,
    _authenticate,
    _preflight,
    _resolve_title,
    _upload_single_video,
    upload_to_youtube,
)
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
        cfg = YouTubeUploadConfig(video_paths=[Path("v.mp4")], privacy_status="secret")
        with pytest.raises(YouTubeUploadError, match="Invalid privacy status"):
            upload_to_youtube(cfg)

    def test_all_files_and_titles_are_checked_before_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"video")
        authenticated = False

        def authenticate(config: YouTubeUploadConfig) -> object:
            nonlocal authenticated
            authenticated = True
            return object()

        monkeypatch.setattr("video_processor.youtube._authenticate", authenticate)
        cfg = YouTubeUploadConfig(
            video_paths=[video, tmp_path / "missing.mp4"],
            title="{name}",
        )

        with pytest.raises(YouTubeUploadError, match="Video file not found"):
            upload_to_youtube(cfg)
        assert authenticated is False

        cfg.video_paths = [video]
        cfg.title = "{unknown}"
        with pytest.raises(YouTubeUploadError, match="Invalid title template"):
            upload_to_youtube(cfg)
        assert authenticated is False


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


def test_valid_cached_token_does_not_require_credentials_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")

    class FakeCredential:
        valid = True
        expired = False
        refresh_token = None

    credential = FakeCredential()

    class FakeCredentials:
        @staticmethod
        def from_authorized_user_file(path: str, scopes: list[str]) -> object:
            return credential

    monkeypatch.setattr("video_processor.youtube._ensure_deps", lambda: None)
    monkeypatch.setattr("video_processor.youtube.Credentials", FakeCredentials)
    monkeypatch.setattr(
        "video_processor.youtube.build",
        lambda service, version, credentials: (service, version, credentials),
    )
    cfg = YouTubeUploadConfig(
        credentials_path=tmp_path / "missing.json",
        token_path=token,
    )

    assert _authenticate(cfg) == ("youtube", "v3", credential)


def test_private_write_is_atomic_mode_0600_and_rejects_symlink(
    tmp_path: Path,
) -> None:
    token = tmp_path / "token.json"
    _atomic_write_private(token, "secret", "token")
    assert token.read_text(encoding="utf-8") == "secret"
    if os.name == "posix":
        assert token.stat().st_mode & 0o777 == 0o600
        target = tmp_path / "target.json"
        target.write_text("safe", encoding="utf-8")
        link = tmp_path / "link.json"
        link.symlink_to(target)
        with pytest.raises(YouTubeUploadError, match="symlink"):
            _atomic_write_private(link, "unsafe", "token")
        assert target.read_text(encoding="utf-8") == "safe"


def test_transient_upload_error_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    attempts = 0

    class TransientError(Exception):
        resp = type("Response", (), {"status": 503})()

    class Request:
        def next_chunk(self) -> tuple[None, dict[str, str] | None]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TransientError("unavailable")
            return None, {"id": "video-id"}

    class Videos:
        def insert(self, **kwargs: Any) -> Request:
            return Request()

    class Service:
        def videos(self) -> Videos:
            return Videos()

    monkeypatch.setattr("video_processor.youtube._ensure_deps", lambda: None)
    monkeypatch.setattr("video_processor.youtube.MediaFileUpload", lambda *a, **k: object())
    monkeypatch.setattr("video_processor.youtube.MediaUploadProgress", object())
    cfg = YouTubeUploadConfig(
        video_paths=[video],
        retry_backoff_seconds=0,
    )

    assert _upload_single_video(cfg, Service(), video, 1, 1, lambda *_args: None) == "video-id"
    assert attempts == 2


def test_upload_ledger_skips_matching_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    cfg = YouTubeUploadConfig(
        video_paths=[video],
        ledger_path=tmp_path / "ledger.json",
    )
    monkeypatch.setattr("video_processor.youtube._authenticate", lambda _cfg: object())
    monkeypatch.setattr(
        "video_processor.youtube._upload_single_video",
        lambda *_args: "video-id",
    )
    assert upload_to_youtube(cfg) == ["video-id"]

    monkeypatch.setattr(
        "video_processor.youtube._authenticate",
        lambda _cfg: pytest.fail("authentication should be skipped"),
    )
    assert upload_to_youtube(cfg) == ["video-id"]


def test_upload_ledger_key_is_scoped_by_token_and_metadata(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    first = YouTubeUploadConfig(
        video_paths=[video],
        token_path=tmp_path / "first-token.json",
        description="first",
    )
    second = YouTubeUploadConfig(
        video_paths=[video],
        token_path=tmp_path / "second-token.json",
        description="second",
    )

    assert _preflight(first) != _preflight(second)

    shared_token = tmp_path / "shared-token.json"
    first.token_path = shared_token
    second.token_path = shared_token
    shared_token.write_text(
        '{"client_id":"client","refresh_token":"account-one"}',
        encoding="utf-8",
    )
    first_key = _preflight(first)
    shared_token.write_text(
        '{"client_id":"client","refresh_token":"account-two"}',
        encoding="utf-8",
    )
    assert first_key != _preflight(second)
