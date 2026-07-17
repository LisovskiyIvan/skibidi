from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .resources import (
    get_default_font_name,
    get_default_font_path,
    get_default_model_dir,
    get_ffmpeg_path,
    get_ffprobe_path,
)


def _default_workers() -> int:
    """Default worker count: balance Vosk (CPU-bound) and FFmpeg (CPU/GPU-bound)."""
    cpus = os.cpu_count() or 4
    # Avoid overwhelming a software encoder; with hardware encoding users can raise.
    return min(4, max(1, cpus // 2))


@dataclass
class PipelineConfig:
    """Configuration for the whole pipeline.

    Keeping configuration in a single dataclass makes it easy to use the same
    pipeline from the CLI, the GUI, or programmatically.
    """

    input: Path
    output_dir: Path = Path("out")
    model_dir: Path = field(default_factory=get_default_model_dir)

    seg_seconds: int = 60

    # Speech-to-text engine selection.
    stt_engine: str = "vosk"
    language: str | None = None
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str | None = None

    burn_subs: bool = True
    subtitle_font: str = field(default_factory=get_default_font_name)
    subtitle_font_path: Path | None = field(default_factory=get_default_font_path)
    subtitle_fontsize: int = 100
    subtitle_pos_y: int = 1500
    fade_in_ms: int = 200
    fade_out_ms: int = 200

    # Fingerprint-evasion / editing options
    mirror: bool = True
    speed: str = "0.95-1.05"
    # When set, all randomized effects (e.g. a speed range) become reproducible.
    # None keeps the default OS-entropy behaviour.
    seed: int | None = None
    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None
    gamma: float | None = None
    hue: float | None = None
    sharpness: bool = False
    noise: int = 0
    overlay_text: str | None = None
    background_audio: Path | None = None
    background_audio_volume: float = 0.3

    # Acceleration and parallelism
    hwaccel: str = "auto"
    video_encoder: str = "auto"
    encoder_preset: str | None = None
    crf: int = 23
    workers: int = field(default_factory=_default_workers)

    ffmpeg: Path | str = field(default_factory=get_ffmpeg_path)
    ffprobe: Path | str = field(default_factory=get_ffprobe_path)
