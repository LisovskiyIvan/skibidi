"""Tests for validation, resume integrity, and fail-fast orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from video_processor.config import PipelineConfig
from video_processor.errors import PipelineError, ProcessCancelledError
from video_processor.ffmpeg import MediaProbe, _resolve_speed
from video_processor.pipeline import _segment_rng, run_pipeline


def _cfg(input_path: Path, output_dir: Path, **overrides: Any) -> PipelineConfig:
    base: dict[str, Any] = {
        "input": input_path,
        "output_dir": output_dir,
        "model_dir": output_dir.parent / "model",
        "seg_seconds": 60,
        "burn_subs": True,
        "seed": 1,
        "video_encoder": "libx264",
        "hwaccel": "none",
    }
    base.update(overrides)
    return PipelineConfig(**base)


def _mock_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    duration: float = 60.0,
    has_audio: bool = True,
) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"engine": [], "wav": [], "render": []}
    monkeypatch.setattr(
        "video_processor.pipeline.probe_media",
        lambda *args, **kwargs: MediaProbe(duration, True, has_audio),
    )

    def create_engine(*_args: Any, **_kwargs: Any) -> object:
        calls["engine"].append(True)
        return _Engine()

    def extract_wav(*args: Any, **kwargs: Any) -> None:
        wav = args[2]
        wav.write_bytes(b"wav")
        calls["wav"].append((args, kwargs))

    def render(*args: Any, **kwargs: Any) -> None:
        final = args[3]
        final.write_bytes(b"valid-video")
        calls["render"].append((args, kwargs))

    def convert(*args: Any, **kwargs: Any) -> None:
        final = args[2]
        final.write_bytes(b"valid-video")
        calls["render"].append((args, kwargs))

    monkeypatch.setattr("video_processor.pipeline.create_stt_engine", create_engine)
    monkeypatch.setattr("video_processor.pipeline.extract_wav", extract_wav)
    monkeypatch.setattr("video_processor.pipeline.burn_subs", render)
    monkeypatch.setattr("video_processor.pipeline.convert_to_9x16", convert)
    return calls


class _Engine:
    def transcribe(self, _wav_path: Path) -> list[Any]:
        return []


class TestPipelineErrors:
    def test_pre_cancelled_pipeline_stops_before_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading

        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        cancelled = threading.Event()
        cancelled.set()
        monkeypatch.setattr(
            "video_processor.pipeline.probe_media",
            lambda *args, **kwargs: pytest.fail("probe must not run"),
        )

        with pytest.raises(ProcessCancelledError, match="cancelled"):
            run_pipeline(_cfg(video, tmp_path / "out", cancel_event=cancelled))

    def test_missing_input_raises_pipeline_error(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path / "missing.mp4", tmp_path / "out")
        with pytest.raises(PipelineError, match="Missing input video"):
            run_pipeline(cfg)

    def test_validation_happens_before_side_effects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        monkeypatch.setattr(
            "video_processor.pipeline.probe_media",
            lambda *args, **kwargs: pytest.fail("probe must not run"),
        )

        with pytest.raises(PipelineError, match="seg_seconds"):
            run_pipeline(_cfg(video, out, seg_seconds=0))

        assert not out.exists()

    def test_missing_model_raises_before_output_creation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        _mock_pipeline(monkeypatch)

        with pytest.raises(PipelineError, match="Missing Vosk model"):
            run_pipeline(_cfg(video, out, model_dir=tmp_path / "missing-model"))

        assert not out.exists()


class TestResume:
    def test_unmanifested_existing_output_is_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        final = out / "final" / "clip_00_sub.mp4"
        final.parent.mkdir(parents=True)
        final.write_bytes(b"untrusted")
        calls = _mock_pipeline(monkeypatch)

        run_pipeline(_cfg(video, out, model_dir=model))

        assert len(calls["render"]) == 1
        assert final.read_bytes() == b"valid-video"

    def test_valid_resume_skips_engine_loading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        calls = _mock_pipeline(monkeypatch)
        cfg = _cfg(video, out, model_dir=model)
        run_pipeline(cfg)
        assert len(calls["engine"]) == 1

        monkeypatch.setattr(
            "video_processor.pipeline.create_stt_engine",
            lambda *_args, **_kwargs: pytest.fail("engine must not load"),
        )
        events: list[str] = []
        run_pipeline(cfg, lambda _step, _cur, _total, msg: events.append(msg))

        assert any("skip existing" in event for event in events)

    def test_changed_render_config_invalidates_resume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        calls = _mock_pipeline(monkeypatch)
        run_pipeline(_cfg(video, out, model_dir=model, mirror=False))
        calls["render"].clear()

        run_pipeline(_cfg(video, out, model_dir=model, mirror=True))

        assert len(calls["render"]) == 1

    def test_changed_input_identity_invalidates_resume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input-one")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        calls = _mock_pipeline(monkeypatch)
        cfg = _cfg(video, out, model_dir=model)
        run_pipeline(cfg)
        calls["render"].clear()
        video.write_bytes(b"input-two-with-different-size")

        run_pipeline(cfg)

        assert len(calls["render"]) == 1

    def test_changed_model_file_invalidates_resume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        model_file = model / "model.conf"
        model_file.write_text("first", encoding="utf-8")
        calls = _mock_pipeline(monkeypatch)
        cfg = _cfg(video, out, model_dir=model)
        run_pipeline(cfg)
        calls["render"].clear()
        model_file.write_text("second-version", encoding="utf-8")

        run_pipeline(cfg)

        assert len(calls["render"]) == 1

    def test_corrupt_or_modified_output_is_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        calls = _mock_pipeline(monkeypatch)
        cfg = _cfg(video, out, model_dir=model)
        run_pipeline(cfg)
        final = out / "final" / "clip_00_sub.mp4"
        final.write_bytes(b"corrupt")
        calls["render"].clear()

        run_pipeline(cfg)

        assert len(calls["render"]) == 1
        assert final.read_bytes() == b"valid-video"

    def test_corrupt_manifest_is_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        calls = _mock_pipeline(monkeypatch)
        cfg = _cfg(video, out, model_dir=model)
        run_pipeline(cfg)
        (out / "final" / "resume-manifest.json").write_text("not-json")
        calls["render"].clear()

        run_pipeline(cfg)

        assert len(calls["render"]) == 1


class TestProcessing:
    def test_processes_source_ranges_without_segment_mp4s(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        calls = _mock_pipeline(monkeypatch, duration=180.0)

        run_pipeline(_cfg(video, out, model_dir=model, workers=2))

        starts = sorted(call[1]["start"] for call in calls["render"])
        assert starts == [0, 60, 120]
        assert not (out / "segments").exists()
        assert not list((out / "wav").glob("*.wav"))

    def test_silent_video_skips_stt_and_audio_mapping_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        calls = _mock_pipeline(monkeypatch, has_audio=False)

        run_pipeline(_cfg(video, out, model_dir=tmp_path / "missing-model"))

        assert calls["engine"] == []
        assert calls["wav"] == []
        assert calls["render"][0][1]["has_audio"] is False

    def test_first_segment_failure_has_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        _mock_pipeline(monkeypatch, duration=180.0)

        def fail(*_args: Any, **_kwargs: Any) -> None:
            raise PipelineError("encoder exploded")

        monkeypatch.setattr("video_processor.pipeline.burn_subs", fail)
        with pytest.raises(PipelineError, match="Segment 0 failed: encoder exploded"):
            run_pipeline(_cfg(video, out, model_dir=model, workers=1))

    def test_failed_rerender_preserves_previous_ass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"input")
        out = tmp_path / "out"
        model = tmp_path / "model"
        model.mkdir()
        _mock_pipeline(monkeypatch)
        run_pipeline(_cfg(video, out, model_dir=model, subtitle_fontsize=80))
        ass_path = out / "srt" / "clip_00.ass"
        original_ass = ass_path.read_text(encoding="utf-8")

        def fail(*_args: Any, **_kwargs: Any) -> None:
            raise PipelineError("render failed")

        monkeypatch.setattr("video_processor.pipeline.burn_subs", fail)
        with pytest.raises(PipelineError, match="render failed"):
            run_pipeline(_cfg(video, out, model_dir=model, subtitle_fontsize=90))

        assert ass_path.read_text(encoding="utf-8") == original_ass
        assert not (out / "srt" / "clip_00.part.ass").exists()

    def test_seed_determinism_is_preserved_across_workers(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path / "video.mp4", tmp_path / "out", speed="0.95-1.05", seed=42)
        speeds_a = [_resolve_speed(cfg.speed, _segment_rng(cfg, idx)) for idx in range(5)]
        speeds_b = [_resolve_speed(cfg.speed, _segment_rng(cfg, idx)) for idx in range(5)]
        assert speeds_a == speeds_b
