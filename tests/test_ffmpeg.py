"""Tests for FFmpeg command building, speed resolution and progress parsing."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from video_processor.config import PipelineConfig
from video_processor.errors import PipelineError
from video_processor.ffmpeg import (
    MediaProbe,
    _build_ffmpeg_cmd,
    _build_video_filter,
    _part_path,
    _resolve_speed,
    convert_to_9x16,
    parse_ffmpeg_seconds,
    probe_media,
)
from video_processor.hwaccel import Acceleration
from video_processor.runtime import ProcessResult


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
        ass = tmp_path / "clip:a,b's.ass"
        filt = _build_video_filter(cfg, ass, 1.0)
        assert "subtitles=filename='" in filt
        assert "clip\\:a\\,b'\\''s.ass'" in filt
        assert "fontsdir='" in filt

    def test_overlay_text_is_filtergraph_escaped(self) -> None:
        filt = _build_video_filter(_config(overlay_text="quote: 'x', [tag]; 100%\nnext"), None, 1.0)
        assert "text='quote\\: '\\''x'\\''\\, \\[tag\\]\\; 100%\\nnext'" in filt
        assert "expansion=none" in filt

    def test_overlay_textfile_path_is_escaped(self, tmp_path: Path) -> None:
        textfile = tmp_path / "overlay:a,b's.txt"
        filt = _build_video_filter(_config(overlay_text="anything"), None, 1.0, textfile)
        assert "textfile='" in filt
        assert "overlay\\:a\\,b'\\''s.txt'" in filt


class TestBuildFfmpegCmd:
    def test_emits_progress_pipe(self) -> None:
        cmd = _build_ffmpeg_cmd(_config(), Path("in.mp4"), Path("out.mp4"), None, random.Random())
        assert "-progress" in cmd
        assert cmd[cmd.index("-progress") + 1] == "pipe:2"

    def test_simple_path_uses_vf(self) -> None:
        cmd = _build_ffmpeg_cmd(_config(), Path("in.mp4"), Path("out.mp4"), None, random.Random())
        assert "-vf" in cmd
        assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"
        assert "0:v:0" in cmd and "0:a:0?" in cmd
        assert "-nostdin" in cmd

    def test_speed_range_uses_filter_complex(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(speed="0.9-1.1"), Path("in.mp4"), Path("out.mp4"), None, random.Random()
        )
        assert "-filter:a:0" in cmd
        assert any(value.startswith("atempo=") for value in cmd)

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
        cmd = _build_ffmpeg_cmd(_config(), Path("in.mp4"), Path("out.mp4"), None, random.Random())
        assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "libx264"
        assert "-preset" in cmd and cmd[cmd.index("-preset") + 1] == "veryfast"
        assert "-crf" in cmd and cmd[cmd.index("-crf") + 1] == "23"

    def test_silent_input_maps_only_first_video(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(),
            Path("silent.mp4"),
            Path("out.mp4"),
            None,
            random.Random(),
            has_audio=False,
        )
        assert "0:v:0" in cmd
        assert "0:a:0?" not in cmd
        assert "[0:a:0]" not in " ".join(cmd)

    def test_explicit_thread_budget_is_used(self) -> None:
        cmd = _build_ffmpeg_cmd(
            _config(encoder_threads=3),
            Path("in.mp4"),
            Path("out.mp4"),
            None,
            random.Random(),
        )
        assert cmd[cmd.index("-threads") + 1] == "3"


def test_probe_media_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = '{"streams":[{"codec_type":"video"}],"format":{"duration":"12.5"}}'
    monkeypatch.setattr(
        "video_processor.ffmpeg.run_process",
        lambda *args, **kwargs: ProcessResult(payload, ""),
    )
    assert probe_media(_config(), Path("silent.mp4")) == MediaProbe(12.5, True, False)


def test_atomic_render_replaces_only_valid_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out.mp4"
    output.write_bytes(b"old")

    def fake_run(_config: PipelineConfig, cmd: list[str], **_kwargs: Any) -> None:
        Path(cmd[-1]).write_bytes(b"new")

    monkeypatch.setattr("video_processor.ffmpeg.run_command", fake_run)
    monkeypatch.setattr(
        "video_processor.ffmpeg.probe_media",
        lambda *args, **kwargs: MediaProbe(1.0, True, False),
    )
    convert_to_9x16(_config(), Path("in.mp4"), output)
    assert output.read_bytes() == b"new"
    assert not _part_path(output).exists()


def test_overlay_textfile_has_safe_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out.mp4"
    seen_text: list[str] = []
    seen_paths: list[Path] = []

    def fake_run(_config: PipelineConfig, cmd: list[str], **_kwargs: Any) -> None:
        video_filter = cmd[cmd.index("-vf") + 1]
        assert "textfile=" in video_filter
        text_path = Path(video_filter.split("textfile='", 1)[1].split("'", 1)[0])
        seen_paths.append(text_path)
        seen_text.append(text_path.read_text(encoding="utf-8"))
        Path(cmd[-1]).write_bytes(b"new")

    monkeypatch.setattr("video_processor.ffmpeg.run_command", fake_run)
    monkeypatch.setattr(
        "video_processor.ffmpeg.probe_media",
        lambda *args, **kwargs: MediaProbe(1.0, True, False),
    )
    convert_to_9x16(_config(overlay_text="arbitrary: 'text' 100%\nnext"), Path("in.mp4"), output)
    assert seen_text == ["arbitrary: 'text' 100%\nnext"]
    assert all(not path.exists() for path in seen_paths)


def test_atomic_render_preserves_old_output_when_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out.mp4"
    output.write_bytes(b"old")

    def fake_run(_config: PipelineConfig, cmd: list[str], **_kwargs: Any) -> None:
        Path(cmd[-1]).write_bytes(b"corrupt")

    monkeypatch.setattr("video_processor.ffmpeg.run_command", fake_run)
    monkeypatch.setattr(
        "video_processor.ffmpeg.probe_media",
        lambda *args, **kwargs: (_ for _ in ()).throw(PipelineError("corrupt")),
    )
    with pytest.raises(PipelineError, match="corrupt"):
        convert_to_9x16(_config(), Path("in.mp4"), output)
    assert output.read_bytes() == b"old"
    assert not _part_path(output).exists()


def test_auto_hardware_failure_retries_with_software(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out.mp4"
    encoders: list[str] = []

    monkeypatch.setattr(
        "video_processor.ffmpeg.resolve_acceleration",
        lambda *args: Acceleration("h264_nvenc", "cuda", True),
    )

    def fake_run(_config: PipelineConfig, cmd: list[str], **_kwargs: Any) -> None:
        encoder = cmd[cmd.index("-c:v") + 1]
        encoders.append(encoder)
        if encoder == "h264_nvenc":
            raise PipelineError("device unavailable")
        Path(cmd[-1]).write_bytes(b"software")

    monkeypatch.setattr("video_processor.ffmpeg.run_command", fake_run)
    monkeypatch.setattr(
        "video_processor.ffmpeg.probe_media",
        lambda *args, **kwargs: MediaProbe(1.0, True, False),
    )

    convert_to_9x16(_config(video_encoder="auto", hwaccel="auto"), Path("in.mp4"), output)

    assert encoders == ["h264_nvenc", "libx264"]
    assert output.read_bytes() == b"software"
