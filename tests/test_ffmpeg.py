"""Tests for FFmpeg command building, speed resolution and progress parsing."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from video_processor.config import PipelineConfig
from video_processor.ffmpeg import (
    _build_ffmpeg_cmd,
    _build_video_filter,
    _resolve_speed,
    parse_ffmpeg_seconds,
)


def _config(**overrides: Any) -> PipelineConfig:
    base: dict[str, Any] = {
        "input": Path("in.mp4"),
        "speed": "1.0",
        "mirror": False,
        "burn_subs": False,
        "video_encoder": "libx264",
        "hwaccel": "none",
    }
    base.update(overrides)
    return PipelineConfig(**base)


class TestResolveSpeed:
    def test_fixed_value(self) -> None:
        assert _resolve_speed("1.0", random.Random(0)) == 1.0

    def test_range_within_bounds(self) -> None:
        for _ in range(100):
            v = _resolve_speed("0.95-1.05", random.Random())
            assert 0.95 <= v <= 1.05

    def test_range_is_reproducible_with_seed(self) -> None:
        a = _resolve_speed("0.95-1.05", random.Random(42))
        b = _resolve_speed("0.95-1.05", random.Random(42))
        assert a == b

    def test_whitespace_tolerant(self) -> None:
        assert _resolve_speed("  1.5 ", random.Random()) == 1.5


class TestParseFfmpegSeconds:
    def test_parses_out_time_ms(self) -> None:
        # 5_120_000 microseconds == 5.12 seconds
        assert parse_ffmpeg_seconds("out_time_ms=5120000") == 5.12

    def test_returns_none_for_unrelated_line(self) -> None:
        assert parse_ffmpeg_seconds("frame=  123 fps= 45") is None

    def test_returns_none_for_empty(self) -> None:
        assert parse_ffmpeg_seconds("") is None

    def test_parses_within_progress_block(self) -> None:
        line = "progress=continue\nout_time_ms=1500000"
        assert parse_ffmpeg_seconds(line) == 1.5


class TestBuildVideoFilter:
    def test_always_includes_scale_and_pad(self) -> None:
        filt = _build_video_filter(_config(), None, 1.0)
        assert "scale=1080:1920:force_original_aspect_ratio=decrease" in filt
        assert "pad=1080:1920" in filt

    def test_mirror_adds_hflip(self) -> None:
        filt = _build_video_filter(_config(mirror=True), None, 1.0)
        assert "hflip" in filt

    def test_eq_params_assembled(self) -> None:
        filt = _build_video_filter(
            _config(brightness=0.05, contrast=1.1, saturation=1.2), None, 1.0
        )
        assert "eq=brightness=0.05:contrast=1.1:saturation=1.2" in filt

    def test_hue_is_separate_filter(self) -> None:
        filt = _build_video_filter(_config(hue=45), None, 1.0)
        assert "hue=H=45" in filt
        assert "eq=" not in filt

    def test_hue_and_eq_can_combine(self) -> None:
        filt = _build_video_filter(_config(brightness=0.1, hue=90), None, 1.0)
        assert "eq=brightness=0.1" in filt
        assert "hue=H=90" in filt

    def test_speed_changes_pts(self) -> None:
        filt = _build_video_filter(_config(), None, 0.9)
        assert "setpts=PTS/0.9" in filt

    def test_subtitles_filter_with_fontsdir(self, tmp_path: Path) -> None:
        font = tmp_path / "Oswald-Bold.ttf"
        font.write_bytes(b"\x00")
        cfg = _config(subtitle_font_path=font)
        ass = tmp_path / "clip.ass"
        filt = _build_video_filter(cfg, ass, 1.0)
        assert f"subtitles={ass.resolve().as_posix()}" in filt
        assert f"fontsdir={tmp_path.resolve().as_posix()}" in filt


class TestBuildFfmpegCmd:
    def test_emits_progress_pipe(self) -> None:
        cmd = _build_ffmpeg_cmd(_config(), Path("in.mp4"), Path("out.mp4"), None, random.Random())
        assert "-progress" in cmd
        assert cmd[cmd.index("-progress") + 1] == "pipe:2"

    def test_simple_path_uses_vf(self) -> None:
        cmd = _build_ffmpeg_cmd(_config(), Path("in.mp4"), Path("out.mp4"), None, random.Random())
        assert "-vf" in cmd
        assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "copy"

    def test_speed_range_uses_filter_complex(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(speed="0.9-1.1"), Path("in.mp4"), Path("out.mp4"), None, random.Random()
        )
        assert "-filter_complex" in cmd
        assert "[v]" in cmd and "[a]" in cmd

    def test_background_audio_loops_second_input(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(background_audio=Path("music.mp3")),
            Path("in.mp4"),
            Path("out.mp4"),
            None,
            random.Random(),
        )
        assert "-stream_loop" in cmd
        assert "music.mp3" in cmd

    def test_hwaccel_none_is_omitted(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(hwaccel="none"), Path("in.mp4"), Path("out.mp4"), None, random.Random()
        )
        assert "-hwaccel" not in cmd

    def test_hwaccel_is_inserted_before_input(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(hwaccel="cuda"), Path("in.mp4"), Path("out.mp4"), None, random.Random()
        )
        assert "-hwaccel" in cmd and cmd[cmd.index("-hwaccel") + 1] == "cuda"
        input_idx = cmd.index("-i")
        hwaccel_idx = cmd.index("-hwaccel")
        assert hwaccel_idx < input_idx

    def test_encoder_and_preset_are_used(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(video_encoder="h264_nvenc", encoder_preset="p6", crf=21),
            Path("in.mp4"),
            Path("out.mp4"),
            None,
            random.Random(),
        )
        assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "h264_nvenc"
        assert "p6" in cmd
        assert "21" in cmd

    def test_default_libx264_uses_veryfast_and_crf(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(), Path("in.mp4"), Path("out.mp4"), None, random.Random()
        )
        assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "libx264"
        assert "-preset" in cmd and cmd[cmd.index("-preset") + 1] == "veryfast"
        assert "-crf" in cmd and cmd[cmd.index("-crf") + 1] == "23"
