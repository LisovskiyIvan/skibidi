"""Low-level FFmpeg helpers and pipeline operations."""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import PipelineConfig
from .constants import (
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    OVERLAY_BOTTOM_MARGIN,
    OVERLAY_FONT_SIZE,
    WAV_CHANNELS,
    WAV_SAMPLE_RATE,
)
from .errors import PipelineError, ProcessCancelledError
from .hwaccel import Acceleration, encoder_args, resolve_acceleration
from .runtime import run_process

# ``out_time_ms`` from ``-progress`` is actually in microseconds (an old FFmpeg
# naming quirk). ``out_time_us`` is the same value under a honest name.
_OUT_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def parse_ffmpeg_seconds(line: str) -> float | None:
    """Return processed seconds from an FFmpeg ``-progress`` line, else None."""
    match = _OUT_TIME_RE.search(line)
    if match is None:
        return None
    return int(match.group(1)) / 1_000_000


@dataclass(frozen=True)
class MediaProbe:
    """Minimal media properties needed by pipeline decisions and validation."""

    duration: float
    has_video: bool
    has_audio: bool


def run_command(
    config: PipelineConfig,
    cmd: list[str],
    on_line: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Run an FFmpeg command with bounded diagnostics and runtime safeguards."""
    run_process(
        cmd,
        timeout=config.ffmpeg_timeout_sec,
        stderr_limit=config.stderr_limit,
        cancel_event=cancel_event,
        on_stderr_line=on_line,
    )


def probe_media(
    config: PipelineConfig,
    path: Path,
    *,
    cancel_event: threading.Event | None = None,
) -> MediaProbe:
    """Probe duration and stream presence using ffprobe's JSON output."""
    cmd = [
        str(config.ffprobe),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,duration",
        "-of",
        "json",
        str(path),
    ]
    result = run_process(
        cmd,
        timeout=config.ffprobe_timeout_sec,
        stderr_limit=config.stderr_limit,
        capture_stdout=True,
        cancel_event=cancel_event,
    )
    try:
        payload: dict[str, Any] = json.loads(result.stdout)
        format_duration = payload.get("format", {}).get("duration")
        stream_durations = [
            float(stream["duration"])
            for stream in payload.get("streams", [])
            if stream.get("duration") not in (None, "N/A")
        ]
        duration = (
            float(format_duration)
            if format_duration not in (None, "N/A")
            else max(stream_durations)
        )
        stream_types = {stream.get("codec_type") for stream in payload.get("streams", [])}
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Invalid ffprobe response for {path}: {exc}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise PipelineError(f"Invalid media duration for {path}: {duration!r}")
    return MediaProbe(
        duration=duration,
        has_video="video" in stream_types,
        has_audio="audio" in stream_types,
    )


def get_duration_sec(config: PipelineConfig, path: Path) -> float:
    """Return video duration in seconds using ffprobe."""
    return probe_media(config, path).duration


def extract_segment(
    config: PipelineConfig,
    input_path: Path,
    start: int,
    duration: int,
    out_mp4: Path,
) -> None:
    """Extract a segment without re-encoding for speed."""
    cmd = [
        str(config.ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-reset_timestamps",
        "1",
        str(out_mp4),
    ]
    run_command(config, cmd)


def extract_wav(
    config: PipelineConfig,
    input_mp4: Path,
    out_wav: Path,
    *,
    start: float | None = None,
    duration: float | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Extract 16kHz mono PCM WAV, optimal for Vosk."""
    cmd = [
        str(config.ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-y",
    ]
    if start is not None:
        cmd.extend(["-ss", str(start)])
    cmd.extend(
        [
            "-i",
            str(input_mp4),
        ]
    )
    if duration is not None:
        cmd.extend(["-t", str(duration)])
    cmd.extend(
        [
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            str(WAV_CHANNELS),
            "-ar",
            str(WAV_SAMPLE_RATE),
            "-f",
            "wav",
            str(out_wav),
        ]
    )
    run_command(config, cmd, cancel_event=cancel_event)


def _nine_by_sixteen_filter() -> str:
    """Video filter that converts any video to 9:16 (1080x1920) with padding."""
    return (
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black"
    )


def _resolve_speed(speed_value: str, rng: random.Random) -> float:
    """Parse a speed value or a range like '0.95-1.05' and return a concrete speed."""
    value = speed_value.strip()
    if "-" in value:
        lo_str, hi_str = value.split("-", 1)
        return rng.uniform(float(lo_str), float(hi_str))
    return float(value)


def _escape_filter_value(value: str) -> str:
    """Quote a filter option value through FFmpeg's filtergraph parser."""
    escaped = value.replace("\\", "\\\\")
    # av_get_token cannot escape a quote while inside a quoted section. Close
    # the section, escape the quote, and reopen it instead.
    escaped = escaped.replace("'", "'\\''")
    for character in (":", ",", "[", "]", ";"):
        escaped = escaped.replace(character, f"\\{character}")
    escaped = escaped.replace("\r", "").replace("\n", "\\n")
    return f"'{escaped}'"


def _build_video_filter(
    config: PipelineConfig,
    ass_path: Path | None,
    speed: float,
    overlay_text_path: Path | None = None,
    subtitle_font_dir: Path | None = None,
) -> str:
    """Build the video filter chain including 9:16, subtitles, and edits."""
    filters = [_nine_by_sixteen_filter()]

    if config.mirror:
        filters.append("hflip")

    if ass_path is not None:
        sub = f"subtitles=filename={_escape_filter_value(ass_path.resolve().as_posix())}"
        if subtitle_font_dir is not None:
            font_dir = subtitle_font_dir.resolve().as_posix()
            sub = f"{sub}:fontsdir={_escape_filter_value(font_dir)}"
        elif config.subtitle_font_path and config.subtitle_font_path.exists():
            font_dir = config.subtitle_font_path.parent.resolve().as_posix()
            sub = f"{sub}:fontsdir={_escape_filter_value(font_dir)}"
        filters.append(sub)

    eq_params = []
    if config.brightness is not None:
        eq_params.append(f"brightness={config.brightness}")
    if config.contrast is not None:
        eq_params.append(f"contrast={config.contrast}")
    if config.saturation is not None:
        eq_params.append(f"saturation={config.saturation}")
    if config.gamma is not None:
        eq_params.append(f"gamma={config.gamma}")
    if eq_params:
        filters.append(f"eq={':'.join(eq_params)}")

    if config.hue is not None:
        filters.append(f"hue=H={config.hue}")

    if config.sharpness:
        filters.append("unsharp")

    if config.noise:
        filters.append(f"noise=alls={config.noise}:allf=t+u")

    if config.overlay_text:
        source = (
            f"textfile={_escape_filter_value(overlay_text_path.resolve().as_posix())}"
            if overlay_text_path is not None
            else f"text={_escape_filter_value(config.overlay_text)}"
        )
        filters.append(
            f"drawtext={source}:expansion=none:reload=0"
            f":x=(w-text_w)/2:y=h-text_h-{OVERLAY_BOTTOM_MARGIN}"
            f":fontsize={OVERLAY_FONT_SIZE}:fontcolor=white"
        )

    if speed != 1.0:
        filters.append(f"setpts=PTS/{speed}")

    return ",".join(filters)


def _build_ffmpeg_cmd(
    config: PipelineConfig,
    input_path: Path,
    out_path: Path,
    ass_path: Path | None,
    rng: random.Random,
    *,
    has_audio: bool = True,
    start: float | None = None,
    duration: float | None = None,
    acceleration: Acceleration | None = None,
    overlay_text_path: Path | None = None,
    subtitle_font_dir: Path | None = None,
) -> list[str]:
    """Build an FFmpeg command that applies 9:16 conversion, subtitles and edits."""
    speed = _resolve_speed(config.speed, rng)
    has_background_audio = config.background_audio is not None
    video_filter = _build_video_filter(
        config,
        ass_path,
        speed,
        overlay_text_path,
        subtitle_font_dir,
    )

    acceleration = acceleration or resolve_acceleration(
        config.ffmpeg, config.video_encoder, config.hwaccel
    )

    cmd = [
        str(config.ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-y",
    ]
    if acceleration.hwaccel is not None:
        cmd.extend(["-hwaccel", acceleration.hwaccel])

    if start is not None:
        cmd.extend(["-ss", str(start)])
    if duration is not None:
        cmd.extend(["-t", str(duration)])
    cmd.extend(["-i", str(input_path)])

    if has_background_audio:
        # Loop the music so it covers the whole video.
        cmd.extend(["-stream_loop", "-1", "-i", str(config.background_audio)])

    cmd.extend(["-vf", video_filter, "-map", "0:v:0"])
    if has_background_audio:
        bg_vol = config.background_audio_volume
        if has_audio:
            original = f"atempo={speed}," if speed != 1.0 else ""
            audio_filter = (
                f"[0:a:0]{original}volume=1.0[orig];"
                f"[1:a:0]volume={bg_vol}[bg];"
                "[orig][bg]amix=inputs=2:duration=first:dropout_transition=2[a]"
            )
        else:
            audio_filter = f"[1:a:0]volume={bg_vol}[a]"
        cmd.extend(["-filter_complex", audio_filter, "-map", "[a]", "-shortest"])
    elif has_audio:
        cmd.extend(["-map", "0:a:0?"])
        if speed != 1.0:
            cmd.extend(["-filter:a:0", f"atempo={speed}"])

    # Structured progress key=value lines on stderr, parsed for live percent.
    thread_budget = config.encoder_threads or max(
        1, (os.cpu_count() or 1) // max(config.workers, 1)
    )
    cmd.extend(
        [
            "-c:v",
            acceleration.encoder,
            *encoder_args(
                acceleration.encoder,
                config.encoder_preset,
                config.crf,
                thread_budget,
            ),
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:2",
            str(out_path),
        ]
    )
    return cmd


def _part_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.part{path.suffix}")


def _render_atomic(
    config: PipelineConfig,
    input_path: Path,
    out_path: Path,
    ass_path: Path | None,
    rng: random.Random,
    on_line: Callable[[str], None] | None,
    has_audio: bool,
    start: float | None,
    duration: float | None,
    cancel_event: threading.Event | None,
) -> None:
    """Render, validate, and atomically publish one output file."""
    part_path = _part_path(out_path)
    part_path.unlink(missing_ok=True)
    acceleration = resolve_acceleration(config.ffmpeg, config.video_encoder, config.hwaccel)
    rng_state = rng.getstate()

    try:
        # Filter resources are staged under generated safe names. This avoids
        # relying on multiple FFmpeg escaping layers for arbitrary user paths.
        with tempfile.TemporaryDirectory(prefix="imperial-ffmpeg-") as temporary:
            staging_dir = Path(temporary)
            staged_ass: Path | None = None
            staged_font_dir: Path | None = None
            overlay_text_path: Path | None = None
            if ass_path is not None:
                staged_ass = staging_dir / "subtitles.ass"
                shutil.copyfile(ass_path, staged_ass)
            if (
                staged_ass is not None
                and config.subtitle_font_path is not None
                and config.subtitle_font_path.is_file()
            ):
                staged_font_dir = staging_dir / "fonts"
                staged_font_dir.mkdir()
                shutil.copyfile(
                    config.subtitle_font_path,
                    staged_font_dir / f"subtitle{config.subtitle_font_path.suffix}",
                )
            if config.overlay_text is not None:
                overlay_text_path = staging_dir / "overlay.txt"
                overlay_text_path.write_text(config.overlay_text, encoding="utf-8")

            def attempt(selection: Acceleration) -> None:
                rng.setstate(rng_state)
                cmd = _build_ffmpeg_cmd(
                    config,
                    input_path,
                    part_path,
                    staged_ass,
                    rng,
                    has_audio=has_audio,
                    start=start,
                    duration=duration,
                    acceleration=selection,
                    overlay_text_path=overlay_text_path,
                    subtitle_font_dir=staged_font_dir,
                )
                run_command(config, cmd, on_line=on_line, cancel_event=cancel_event)
                probe = probe_media(config, part_path, cancel_event=cancel_event)
                if not probe.has_video:
                    raise PipelineError(f"Rendered output has no video stream: {part_path}")

            try:
                attempt(acceleration)
            except ProcessCancelledError:
                raise
            except PipelineError:
                if not acceleration.auto_hardware:
                    raise
                part_path.unlink(missing_ok=True)
                attempt(Acceleration("libx264", None, False))
            part_path.replace(out_path)
    finally:
        part_path.unlink(missing_ok=True)


def convert_to_9x16(
    config: PipelineConfig,
    input_mp4: Path,
    out_mp4: Path,
    *,
    rng: random.Random | None = None,
    on_line: Callable[[str], None] | None = None,
    has_audio: bool = True,
    start: float | None = None,
    duration: float | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Convert a video to 9:16, optionally applying edits and background audio."""
    _render_atomic(
        config,
        input_mp4,
        out_mp4,
        None,
        rng or random.Random(),
        on_line,
        has_audio,
        start,
        duration,
        cancel_event,
    )


def burn_subs(
    config: PipelineConfig,
    input_mp4: Path,
    ass_path: Path,
    out_mp4: Path,
    *,
    rng: random.Random | None = None,
    on_line: Callable[[str], None] | None = None,
    has_audio: bool = True,
    start: float | None = None,
    duration: float | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Convert to 9:16, burn an ASS subtitle file and apply edits/audio."""
    _render_atomic(
        config,
        input_mp4,
        out_mp4,
        ass_path,
        rng or random.Random(),
        on_line,
        has_audio,
        start,
        duration,
        cancel_event,
    )
