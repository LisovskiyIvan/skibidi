"""Tests for PipelineConfig defaults and serialization."""

from pathlib import Path

from video_processor.config import PipelineConfig


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
    d = cfg.as_dict()
    assert d["input"] == "v.mp4"
    assert d["seed"] == 7
    assert d["brightness"] == 0.1
    assert "ffmpeg" in d and "ffprobe" in d
    # Every dataclass field is represented.
    assert set(d) >= {"input", "output_dir", "model_dir", "seg_seconds", "burn_subs"}


def test_optional_effect_fields_default_none() -> None:
    cfg = PipelineConfig(input=Path("v.mp4"))
    for field in ("brightness", "contrast", "saturation", "gamma", "hue", "overlay_text"):
        assert getattr(cfg, field) is None
