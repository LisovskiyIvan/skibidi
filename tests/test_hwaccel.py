"""Tests for FFmpeg hardware acceleration / encoder detection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import video_processor.hwaccel as hwaccel
from video_processor.hwaccel import (
    encoder_args,
    resolve_encoder,
    resolve_hwaccel,
)


@pytest.fixture(autouse=True)
def _clear_hwaccel_cache() -> None:
    """Ensure each test starts with a clean encoder detection cache."""
    hwaccel._cache.clear()


class TestResolveEncoder:
    def test_explicit_encoder_is_returned(self) -> None:
        assert resolve_encoder("ffmpeg", "h264_nvenc") == "h264_nvenc"
        assert resolve_encoder("ffmpeg", "libx264") == "libx264"

    def test_auto_selects_first_available(self) -> None:
        stdout = (
            "Encoders:\n"
            " V..... libx264              libx264 H.264 / AVC / MPEG-4 AVC\n"
            " V....D h264_nvenc           NVIDIA NVENC H.264 encoder\n"
        )
        with patch(
            "video_processor.hwaccel.subprocess.run",
            return_value=_mock_proc(stdout),
        ):
            assert resolve_encoder("ffmpeg", "auto") == "h264_nvenc"

    def test_auto_falls_back_to_libx264(self) -> None:
        stdout = "Encoders:\n V..... libx264              libx264 H.264 / AVC\n"
        with patch(
            "video_processor.hwaccel.subprocess.run",
            return_value=_mock_proc(stdout),
        ):
            assert resolve_encoder("ffmpeg", "auto") == "libx264"

    def test_auto_falls_back_when_ffmpeg_fails(self) -> None:
        with patch(
            "video_processor.hwaccel.subprocess.run",
            return_value=_mock_proc("", returncode=1),
        ):
            assert resolve_encoder("ffmpeg", "auto") == "libx264"

    def test_caches_encoder_result(self) -> None:
        stdout = "Encoders:\n V....D h264_nvenc           H.264\n"
        with patch(
            "video_processor.hwaccel.subprocess.run",
            return_value=_mock_proc(stdout),
        ) as mock_run:
            assert resolve_encoder("ffmpeg", "auto") == "h264_nvenc"
            assert resolve_encoder("ffmpeg", "auto") == "h264_nvenc"
            # Second call should reuse the cached probe result.
            assert mock_run.call_count == 1


class TestResolveHwaccel:
    def test_explicit_value_is_returned(self) -> None:
        assert resolve_hwaccel("ffmpeg", "cuda") == "cuda"
        assert resolve_hwaccel("ffmpeg", "none") is None

    def test_none_disables_hwaccel(self) -> None:
        assert resolve_hwaccel("ffmpeg", "none") is None

    def test_auto_maps_to_detected_encoder(self) -> None:
        stdout = "Encoders:\n V....D h264_qsv             Intel QSV H.264\n"
        with patch(
            "video_processor.hwaccel.subprocess.run",
            return_value=_mock_proc(stdout),
        ):
            assert resolve_hwaccel("ffmpeg", "auto") == "qsv"


class TestEncoderArgs:
    def test_libx264_uses_crf_and_threads(self) -> None:
        args = encoder_args("libx264", None, 23)
        assert "-crf" in args
        assert "23" in args
        assert "-threads" in args
        assert "0" in args
        assert "veryfast" in args

    def test_libx264_preset_override(self) -> None:
        args = encoder_args("libx264", "ultrafast", 23)
        assert "ultrafast" in args

    def test_nvenc_uses_cq(self) -> None:
        args = encoder_args("h264_nvenc", None, 23)
        assert "-cq" in args
        assert "23" in args
        assert "p5" in args

    def test_qsv_uses_global_quality(self) -> None:
        args = encoder_args("h264_qsv", None, 23)
        assert "-global_quality" in args
        assert "23" in args


def _mock_proc(stdout: str, returncode: int = 0) -> object:
    class _Proc:
        pass

    proc = _Proc()
    proc.stdout = stdout
    proc.stderr = ""
    proc.returncode = returncode
    return proc
