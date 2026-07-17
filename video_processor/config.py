from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from .errors import PipelineError
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
    encoder_threads: int | None = None

    # Runtime safeguards. FFmpeg renders may legitimately take many minutes;
    # probes should never do so.
    ffmpeg_timeout_sec: float = 3600.0
    ffprobe_timeout_sec: float = 30.0
    stderr_limit: int = 64 * 1024
    keep_intermediates: bool = False
    cancel_event: Event | None = field(default=None, repr=False, compare=False)

    ffmpeg: Path | str = field(default_factory=get_ffmpeg_path)
    ffprobe: Path | str = field(default_factory=get_ffprobe_path)

    def validate(self) -> None:
        """Validate all configuration invariants without causing side effects."""
        errors: list[str] = []
        if self.seg_seconds <= 0:
            errors.append("seg_seconds must be greater than zero")
        if self.workers <= 0:
            errors.append("workers must be greater than zero")
        if self.encoder_threads is not None and self.encoder_threads <= 0:
            errors.append("encoder_threads must be greater than zero when set")
        if self.ffmpeg_timeout_sec <= 0 or self.ffprobe_timeout_sec <= 0:
            errors.append("subprocess timeouts must be greater than zero")
        if self.stderr_limit < 1024:
            errors.append("stderr_limit must be at least 1024 bytes")
        if self.stt_engine.lower() not in {"vosk", "whisper"}:
            errors.append("stt_engine must be 'vosk' or 'whisper'")
        if self.whisper_device not in {"auto", "cpu", "cuda"}:
            errors.append("whisper_device must be 'auto', 'cpu', or 'cuda'")
        if not str(self.ffmpeg) or not str(self.ffprobe):
            errors.append("ffmpeg and ffprobe executables must be set")
        if not self.video_encoder or not self.hwaccel:
            errors.append("video_encoder and hwaccel must be set")
        if self.subtitle_fontsize <= 0:
            errors.append("subtitle_fontsize must be greater than zero")
        if self.fade_in_ms < 0 or self.fade_out_ms < 0:
            errors.append("subtitle fades cannot be negative")
        if not 0 <= self.crf <= 51:
            errors.append("crf must be between 0 and 51")
        if self.background_audio_volume < 0:
            errors.append("background_audio_volume cannot be negative")
        numeric_ranges = (
            ("brightness", self.brightness, -1.0, 1.0),
            ("contrast", self.contrast, -1000.0, 1000.0),
            ("saturation", self.saturation, 0.0, 3.0),
            ("gamma", self.gamma, 0.1, 10.0),
        )
        for name, value, low, high in numeric_ranges:
            if value is not None and (not math.isfinite(value) or value < low or value > high):
                errors.append(f"{name} must be between {low:g} and {high:g}")
        if not math.isfinite(self.background_audio_volume):
            errors.append("background_audio_volume must be finite")
        if not 0 <= self.noise <= 100:
            errors.append("noise must be between 0 and 100")

        try:
            values = self.speed.strip().split("-", 1)
            low = float(values[0])
            high = float(values[-1])
            if (
                not math.isfinite(low)
                or not math.isfinite(high)
                or low > high
                or low < 0.5
                or high > 2.0
            ):
                raise ValueError
        except (AttributeError, ValueError):
            errors.append("speed must be a number or range between 0.5 and 2.0")

        if errors:
            raise PipelineError("Invalid pipeline configuration: " + "; ".join(errors))
