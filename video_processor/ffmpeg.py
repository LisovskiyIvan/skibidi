"""Low-level FFmpeg helpers and pipeline operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import PipelineConfig


def run_command(config: PipelineConfig, cmd: list[str]) -> None:
    """Run a subprocess and raise a clear error on failure."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed:\n{' '.join(cmd)}\n\nSTDERR:\n{proc.stderr}")


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
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{proc.stderr}")
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


def convert_to_9x16(config: PipelineConfig, input_mp4: Path, out_mp4: Path) -> None:
    """Convert a video to 9:16 without burning subtitles."""
    cmd = [
        str(config.ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(input_mp4),
        "-vf",
        _nine_by_sixteen_filter(),
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        str(out_mp4),
    ]
    run_command(config, cmd)


def burn_subs(
    config: PipelineConfig,
    input_mp4: Path,
    ass_path: Path,
    out_mp4: Path,
) -> None:
    """Convert to 9:16 and burn an ASS subtitle file into the result."""
    # First scale/pad, then render subtitles so the ASS coordinates match the
    # 1080x1920 output frame.
    video_filter = f"{_nine_by_sixteen_filter()},subtitles={ass_path.as_posix()}"

    # Let libass find bundled fonts by pointing it at the font directory.
    if config.subtitle_font_path and config.subtitle_font_path.exists():
        font_dir = config.subtitle_font_path.parent.as_posix()
        video_filter = f"{video_filter}:fontsdir={font_dir}"

    cmd = [
        str(config.ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(input_mp4),
        "-vf",
        video_filter,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        str(out_mp4),
    ]
    run_command(config, cmd)
