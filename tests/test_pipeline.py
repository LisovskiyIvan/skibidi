"""Tests for the pipeline orchestration (error handling + resume/skip)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from video_processor.config import PipelineConfig
from video_processor.errors import PipelineError
from video_processor.pipeline import run_pipeline


def _cfg(input_path: Path, output_dir: Path, **overrides: Any) -> PipelineConfig:
    base: dict[str, Any] = dict(
        input=input_path,
        output_dir=output_dir,
        model_dir=Path("vosk-model-small-ru-0.22"),
        seg_seconds=60,
        burn_subs=True,
        seed=1,
    )
    base.update(overrides)
    return PipelineConfig(**base)


class TestPipelineErrors:
    def test_missing_input_raises_pipeline_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Avoid touching the real model dir / ffmpeg.
        monkeypatch.setattr("video_processor.pipeline.get_duration_sec", lambda *a, **k: 0.0)
        cfg = _cfg(tmp_path / "missing.mp4", tmp_path / "out")
        with pytest.raises(PipelineError, match="Missing input video"):
            run_pipeline(cfg)

    def test_missing_model_raises_pipeline_error(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00")
        cfg = _cfg(video, tmp_path / "out", model_dir=tmp_path / "no-such-model")
        with pytest.raises(PipelineError, match="Missing Vosk model"):
            run_pipeline(cfg)


class TestResumeSkip:
    def test_existing_final_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00")

        out = tmp_path / "out"
        final_dir = out / "final"
        final_dir.mkdir(parents=True)
        # Pre-render segment 0 so the pipeline must skip it.
        (final_dir / "clip_00_sub.mp4").write_bytes(b"\x00")

        calls: dict[str, list[int]] = {"segment": [], "burn": []}

        monkeypatch.setattr("video_processor.pipeline.get_duration_sec", lambda *a, **k: 120.0)
        monkeypatch.setattr("video_processor.pipeline.load_model", lambda *a, **k: object())
        monkeypatch.setattr(
            "video_processor.pipeline.extract_segment",
            lambda *a, **k: calls["segment"].append(a[2]),
        )
        monkeypatch.setattr("video_processor.pipeline.extract_wav", lambda *a, **k: None)
        monkeypatch.setattr(
            "video_processor.pipeline.transcribe_to_cues", lambda *a, **k: []
        )
        monkeypatch.setattr("video_processor.pipeline.burn_subs", lambda *a, **k: calls["burn"].append(a[3]))

        events: list[str] = []
        run_pipeline(_cfg(video, out), lambda step, cur, total, msg: events.append(msg))

        # Segment 0 skipped, only segment 1 processed.
        assert calls["segment"] == [60]
        assert calls["burn"] != []
        assert any("skip existing" in e for e in events)
