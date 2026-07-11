"""Low-level FFmpeg helpers and pipeline operations."""

from __future__ import annotations

import random
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import PipelineConfig
from .errors import PipelineError
from .hwaccel import encoder_args, resolve_encoder, resolve_hwaccel

# ``out_time_ms`` from ``-progress`` is actually in microseconds (an old FFmpeg
# naming quirk). ``out_time_us`` is the same value under a honest name.
_OUT_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def parse_ffmpeg_seconds(line: str) -> float | None:
    """Return processed seconds from an FFmpeg ``-progress`` line, else None."""
    match = _OUT_TIME_RE.search(line)
    if match is None:
        return None
    return int(match.group(1)) / 1_000_000


def _failed_message(cmd: list[str], stderr: str) -> str:
    return f"Command failed:\n{' '.join(cmd)}\n\nSTDERR:\n{stderr}"


def run_command(
    config: PipelineConfig,
    cmd: list[str],
    on_line: Callable[[str], None] | None = None,
) -> None:
    """Run a subprocess and raise :class:`PipelineError` on failure.

    When ``on_line`` is provided, FFmpeg's stderr is streamed line by line so
    the caller can report live progress (see :func:`parse_ffmpeg_seconds`).
    Otherwise stderr is captured fully, as before.
    """
    if on_line is None:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise PipelineError(_failed_message(cmd, proc.stderr))
        return

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    tail: list[str] = []
    try:
        assert process.stderr is not None
        for line in process.stderr:
            on_line(line.rstrip("\r\n"))
            tail.append(line)
            if len(tail) > 50:
                tail.pop(0)
        process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
    if process.returncode != 0:
        raise PipelineError(_failed_message(cmd, "".join(tail)))


def get_duration_sec(config: PipelineConfig, path: Path) -> float:
    """Return video duration in seconds using ffprobe."""
    cmd = [
        str(config.ffprobe),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise PipelineError(f"ffprobe failed:\n{proc.stderr}")
    return float(proc.stdout.strip())


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
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(input_path),
        "-map",
        "0",
        "-c",
        "copy",
        "-reset_timestamps",
        "1",
        str(out_mp4),
    ]
    run_command(config, cmd)


def extract_wav(config: PipelineConfig, input_mp4: Path, out_wav: Path) -> None:
    """Extract 16kHz mono PCM WAV, optimal for Vosk."""
    cmd = [
        str(config.ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(input_mp4),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(out_wav),
    ]
    run_command(config, cmd)


def _nine_by_sixteen_filter() -> str:
    """Video filter that converts any video to 9:16 (1080x1920) with padding."""
    return (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
    )


def _resolve_speed(speed_value: str, rng: random.Random) -> float:
    """Parse a speed value or a range like '0.95-1.05' and return a concrete speed."""
    value = speed_value.strip()
    if "-" in value:
        lo_str, hi_str = value.split("-", 1)
        return rng.uniform(float(lo_str), float(hi_str))
    return float(value)


def _build_video_filter(config: PipelineConfig, ass_path: Path | None, speed: float) -> str:
    """Build the video filter chain including 9:16, subtitles, and edits."""
    filters = [_nine_by_sixteen_filter()]

    if config.mirror:
        filters.append("hflip")

    if ass_path is not None:
        sub = f"subtitles={ass_path.resolve().as_posix()}"
        if config.subtitle_font_path and config.subtitle_font_path.exists():
            font_dir = config.subtitle_font_path.parent.resolve().as_posix()
            sub = f"{sub}:fontsdir={font_dir}"
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
        # Basic escaping for single quotes in drawtext
        text = config.overlay_text.replace("'", "\\'")
        filters.append(
            "drawtext=text='"
            f"{text}"
            ":x=(w-text_w)/2:y=h-text_h-50:fontsize=24:fontcolor=white"
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
) -> list[str]:
    """Build an FFmpeg command that applies 9:16 conversion, subtitles and edits."""
    speed = _resolve_speed(config.speed, rng)
    has_background_audio = config.background_audio is not None
    needs_complex = has_background_audio or speed != 1.0
    video_filter = _build_video_filter(config, ass_path, speed)

    encoder = resolve_encoder(config.ffmpeg, config.video_encoder)
    hwaccel = resolve_hwaccel(config.ffmpeg, config.hwaccel)

    cmd = [
        str(config.ffmpeg),
        "-hide_banner",
        "-y",
    ]
    if hwaccel is not None and hwaccel != "none":
        cmd.extend(["-hwaccel", hwaccel])

    cmd.extend(["-i", str(input_path)])

    if has_background_audio:
        # Loop the music so it covers the whole video.
        cmd.extend(["-stream_loop", "-1", "-i", str(config.background_audio)])

    if needs_complex:
        audio_chains: list[str] = []
        if has_background_audio:
            bg_vol = config.background_audio_volume
            if speed != 1.0:
                audio_chains.append(f"[0:a]atempo={speed}[a_sped]")
                audio_chains.append("[a_sped]volume=1.0[orig]")
            else:
                audio_chains.append("[0:a]volume=1.0[orig]")
            audio_chains.append(f"[1:a]volume={bg_vol}[bg]")
            audio_chains.append(
                "[orig][bg]amix=inputs=2:duration=first:dropout_transition=2[a]"
            )
        else:
            audio_chains.append(f"[0:a]atempo={speed}[a]")

        filter_complex = f"{';'.join(audio_chains)};[0:v]{video_filter}[v]"
        cmd.extend([
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
        ])
    else:
        cmd.extend(["-vf", video_filter, "-c:a", "copy"])

    # Structured progress key=value lines on stderr, parsed for live percent.
    cmd.extend(
        [
            "-c:v",
            encoder,
            *encoder_args(encoder, config.encoder_preset, config.crf),
            "-progress",
            "pipe:2",
            str(out_path),
        ]
    )
    return cmd


def convert_to_9x16(
    config: PipelineConfig,
    input_mp4: Path,
    out_mp4: Path,
    *,
    rng: random.Random | None = None,
    on_line: Callable[[str], None] | None = None,
) -> None:
    """Convert a video to 9:16, optionally applying edits and background audio."""
    cmd = _build_ffmpeg_cmd(config, input_mp4, out_mp4, ass_path=None, rng=rng or random.Random())
    run_command(config, cmd, on_line=on_line)


def burn_subs(
    config: PipelineConfig,
    input_mp4: Path,
    ass_path: Path,
    out_mp4: Path,
    *,
    rng: random.Random | None = None,
    on_line: Callable[[str], None] | None = None,
) -> None:
    """Convert to 9:16, burn an ASS subtitle file and apply edits/audio."""
    cmd = _build_ffmpeg_cmd(config, input_mp4, out_mp4, ass_path=ass_path, rng=rng or random.Random())
    run_command(config, cmd, on_line=on_line)
