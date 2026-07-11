"""Hardware acceleration and encoder detection for FFmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

# Preferred order: NVIDIA > Intel QSV > AMD > macOS VideoToolbox > software.
_ENCODER_PRIORITY: Final[tuple[str, ...]] = (
    "h264_nvenc",
    "h264_qsv",
    "h264_amf",
    "h264_videotoolbox",
    "libx264",
)


# Cache results keyed by ffmpeg executable path so we probe only once per process.
_cache: dict[str, tuple[str, list[str]]] = {}


def _list_encoders(ffmpeg: Path | str) -> list[str]:
    """Return the list of available H.264 encoders from ``ffmpeg -encoders``."""
    proc = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []

    encoders: list[str] = []
    for line in proc.stdout.splitlines():
        if "H.264" not in line:
            continue
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        name = parts[1]
        if name not in _ENCODER_PRIORITY:
            continue
        encoders.append(name)
    return encoders


def _probe(ffmpeg: Path | str) -> tuple[str, list[str]]:
    """Return (chosen_encoder, available_h264_encoders)."""
    key = str(ffmpeg)
    if key in _cache:
        return _cache[key]

    available = _list_encoders(ffmpeg)
    chosen = "libx264"  # safe fallback
    for encoder in _ENCODER_PRIORITY:
        if encoder in available:
            chosen = encoder
            break

    result = (chosen, available)
    _cache[key] = result
    return result


def resolve_encoder(ffmpeg: Path | str, explicit: str | None) -> str:
    """Resolve the requested encoder name or auto-detect the best available one.

    ``explicit`` values ``None`` and ``"auto"`` mean auto-detection. Any other
    value is returned as-is and assumed to be a valid FFmpeg encoder name.
    """
    if explicit is None or explicit == "auto":
        return _probe(ffmpeg)[0]
    return explicit


def resolve_hwaccel(ffmpeg: Path | str, explicit: str | None) -> str | None:
    """Resolve the hardware acceleration method.

    ``None``/``"auto"`` select an acceleration matching the detected encoder.
    ``"none"`` disables it entirely. Other values are passed to FFmpeg verbatim.
    """
    if explicit is None or explicit == "auto":
        encoder = _probe(ffmpeg)[0]
        mapping = {
            "h264_nvenc": "cuda",
            "h264_qsv": "qsv",
            "h264_amf": "d3d11va",
            "h264_videotoolbox": "videotoolbox",
            "libx264": "auto",
        }
        return mapping.get(encoder, "auto")
    if explicit == "none":
        return None
    return explicit


def encoder_args(encoder: str, preset: str | None, quality: int) -> list[str]:
    """Return encoder-specific FFmpeg output arguments.

    The returned list is ready to extend into the command after ``-c:v``.
    """
    if encoder == "h264_nvenc":
        # NVENC uses CQ quality mode. Preset p4/p5 is a good quality/speed balance.
        chosen_preset = preset or "p5"
        return [
            "-preset",
            chosen_preset,
            "-rc",
            "vbr",
            "-cq",
            str(quality),
        ]
    if encoder == "h264_qsv":
        # Intel QSV uses global_quality; map CRF-style value directly.
        chosen_preset = preset or "veryfast"
        return [
            "-preset",
            chosen_preset,
            "-global_quality",
            str(quality),
            "-look_ahead",
            "0",
        ]
    if encoder == "h264_amf":
        # AMD AMF uses I/P frame QP values.
        chosen_preset = preset or "quality"
        return [
            "-preset",
            chosen_preset,
            "-qp_i",
            str(quality),
            "-qp_p",
            str(quality),
        ]
    if encoder == "h264_videotoolbox":
        # Apple VideoToolbox has limited quality control; use qscale-ish argument.
        chosen_preset = preset or "high"
        return [
            "-preset",
            chosen_preset,
            "-q:v",
            str(quality),
        ]
    # libx264 / libx265 style software encoders.
    chosen_preset = preset or "veryfast"
    return [
        "-preset",
        chosen_preset,
        "-crf",
        str(quality),
        "-threads",
        "0",
    ]
