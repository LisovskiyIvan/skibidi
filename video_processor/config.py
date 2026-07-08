from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .resources import (
    get_default_font_name,
    get_default_font_path,
    get_default_model_dir,
    get_ffmpeg_path,
    get_ffprobe_path,
)


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

    ffmpeg: Path | str = field(default_factory=get_ffmpeg_path)
    ffprobe: Path | str = field(default_factory=get_ffprobe_path)

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": str(self.input),
            "output_dir": str(self.output_dir),
            "model_dir": str(self.model_dir),
            "seg_seconds": self.seg_seconds,
            "burn_subs": self.burn_subs,
            "subtitle_font": self.subtitle_font,
            "subtitle_font_path": str(self.subtitle_font_path) if self.subtitle_font_path else None,
            "subtitle_fontsize": self.subtitle_fontsize,
            "subtitle_pos_y": self.subtitle_pos_y,
            "fade_in_ms": self.fade_in_ms,
            "fade_out_ms": self.fade_out_ms,
            "mirror": self.mirror,
            "speed": self.speed,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "saturation": self.saturation,
            "gamma": self.gamma,
            "hue": self.hue,
            "sharpness": self.sharpness,
            "noise": self.noise,
            "overlay_text": self.overlay_text,
            "background_audio": str(self.background_audio) if self.background_audio else None,
            "background_audio_volume": self.background_audio_volume,
            "ffmpeg": str(self.ffmpeg),
            "ffprobe": str(self.ffprobe),
        }
