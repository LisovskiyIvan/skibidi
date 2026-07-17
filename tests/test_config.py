"""Tests for PipelineConfig defaults and serialization."""

from dataclasses import asdict
from pathlib import Path

import pytest

from video_processor.config import PipelineConfig
from video_processor.errors import PipelineError


def test_defaults() -> None:
    cfg = PipelineConfig(input=Path("v.mp4"))
    assert cfg.output_dir == Path("out")
    assert cfg.seg_seconds == 60
    assert cfg.burn_subs is True
    assert cfg.mirror is True
    assert cfg.speed == "0.95-1.05"
    assert cfg.seed is None
    assert cfg.noise == 0


def test_as_dict_round_trip_keys() -> None:
    cfg = PipelineConfig(input=Path("v.mp4"), seed=7, brightness=0.1)
    d = asdict(cfg)
    assert d["input"] == Path("v.mp4")
    assert d["seed"] == 7
    assert d["brightness"] == 0.1
    assert "ffmpeg" in d and "ffprobe" in d
    # Every dataclass field is represented.
    assert set(d) >= {"input", "output_dir", "model_dir", "seg_seconds", "burn_subs"}


def test_optional_effect_fields_default_none() -> None:
    cfg = PipelineConfig(input=Path("v.mp4"))
    for field in ("brightness", "contrast", "saturation", "gamma", "hue", "overlay_text"):
        assert getattr(cfg, field) is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"seg_seconds": 0}, "seg_seconds"),
        ({"workers": 0}, "workers"),
        ({"speed": "fast"}, "speed"),
        ({"speed": "0.1-3.0"}, "speed"),
        ({"crf": 99}, "crf"),
        ({"ffmpeg_timeout_sec": 0}, "timeouts"),
        ({"stt_engine": "unknown"}, "stt_engine"),
    ],
)
def test_validation_rejects_invalid_values(overrides: dict[str, object], message: str) -> None:
    cfg = PipelineConfig(input=Path("v.mp4"), **overrides)  # type: ignore[arg-type]
    with pytest.raises(PipelineError, match=message):
        cfg.validate()


def test_validation_accepts_valid_config() -> None:
    PipelineConfig(input=Path("v.mp4"), speed="0.5-2.0", encoder_threads=2).validate()
