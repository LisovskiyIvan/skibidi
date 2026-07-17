"""Tests for the speech-to-text engine factory and adapters (mocked)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from video_processor.config import PipelineConfig
from video_processor.errors import PipelineError
from video_processor.transcribe import SpeechToText, create_stt_engine


def _cfg(**overrides: Any) -> PipelineConfig:
    base: dict[str, Any] = {"input": Path("in.mp4")}
    base.update(overrides)
    return PipelineConfig(**base)

class TestCreateEngine:
    def test_unknown_engine_raises(self) -> None:
        with pytest.raises(PipelineError, match="Unknown STT engine"):
            create_stt_engine(_cfg(stt_engine="nonsense"))

    def test_vosk_engine_is_speech_to_text(self, tmp_path: Path) -> None:
        with patch("video_processor.stt_vosk.Model") as mock_model:
            engine = create_stt_engine(_cfg(stt_engine="vosk", model_dir=tmp_path))
        assert isinstance(engine, SpeechToText)
        mock_model.assert_called_once_with(str(tmp_path))

    def test_whisper_engine_is_speech_to_text(self) -> None:
        fake_module = _install_fake_faster_whisper()
        try:
            engine = create_stt_engine(
                _cfg(stt_engine="whisper", whisper_device="cpu", language="ru")
            )
            assert isinstance(engine, SpeechToText)
            fake_module.WhisperModel.assert_called_once()
        finally:
            sys.modules.pop("faster_whisper", None)

    def test_whisper_without_dependency_raises(self) -> None:
        # Ensure faster_whisper is not importable.
        sys.modules.pop("faster_whisper", None)
        original = sys.modules.get("faster_whisper")
        with patch.dict(sys.modules, {"faster_whisper": None}):
            with pytest.raises(PipelineError, match="faster-whisper is not installed"):
                create_stt_engine(_cfg(stt_engine="whisper"))
        if original is not None:
            sys.modules["faster_whisper"] = original


class TestWhisperDeviceDetection:
    def test_preload_is_safe_when_nvidia_packages_absent(self) -> None:
        # No nvidia packages installed -> preload must be a no-op (no exception).
        with patch.dict(sys.modules, {"nvidia.cublas": None, "nvidia.cudnn": None}):
            from video_processor.stt_whisper import _preload_cuda_libraries

            _preload_cuda_libraries()  # should not raise

    def test_preload_called_for_cuda(self) -> None:
        from video_processor.stt_whisper import _build_whisper_model

        class FakeModel:
            def __init__(self, model: str, device: str, compute_type: str) -> None:
                self.device = device

        cfg = _cfg(stt_engine="whisper", whisper_device="cuda", whisper_model="small")
        with patch(
            "video_processor.stt_whisper._preload_cuda_libraries"
        ) as mock_preload:
            _build_whisper_model(FakeModel, cfg, "cuda", fallback=True)
        mock_preload.assert_called_once()

    def test_preload_not_called_for_cpu(self) -> None:
        from video_processor.stt_whisper import _build_whisper_model

        class FakeModel:
            def __init__(self, model: str, device: str, compute_type: str) -> None:
                self.device = device

        cfg = _cfg(stt_engine="whisper", whisper_device="cpu", whisper_model="small")
        with patch(
            "video_processor.stt_whisper._preload_cuda_libraries"
        ) as mock_preload:
            _build_whisper_model(FakeModel, cfg, "cpu", fallback=True)
        mock_preload.assert_not_called()

    def test_explicit_device_returned(self) -> None:
        from video_processor.stt_whisper import _detect_device

        assert _detect_device("cpu") == "cpu"
        assert _detect_device("cuda") == "cuda"

    def test_auto_falls_back_to_cpu_without_cuda(self) -> None:
        from video_processor.stt_whisper import _detect_device

        fake_ct2 = MagicMock()
        fake_ct2.get_cuda_device_count.return_value = 0
        with patch.dict(sys.modules, {"ctranslate2": fake_ct2}):
            assert _detect_device("auto") == "cpu"

    def test_auto_uses_cuda_when_available(self) -> None:
        from video_processor.stt_whisper import _detect_device

        fake_ct2 = MagicMock()
        fake_ct2.get_cuda_device_count.return_value = 1
        with patch.dict(sys.modules, {"ctranslate2": fake_ct2}):
            assert _detect_device("auto") == "cuda"

    def test_default_compute_type(self) -> None:
        from video_processor.stt_whisper import _default_compute_type

        assert _default_compute_type("cuda") == "float16"
        assert _default_compute_type("cpu") == "int8"


class TestWhisperTranscribe:
    def test_transcribe_maps_words(self) -> None:
        from video_processor.stt_whisper import WhisperEngine

        model = MagicMock()
        segment = MagicMock()
        w1 = MagicMock(start=0.0, end=0.5, word="  hello")
        w2 = MagicMock(start=0.6, end=0.9, word="world")
        segment.words = [w1, w2]
        model.transcribe.return_value = ([segment], MagicMock())

        engine = WhisperEngine(model, language="ru")
        words = engine.transcribe(Path("clip.wav"))

        model.transcribe.assert_called_once()
        assert words == [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.6, "end": 0.9},
        ]

    def test_transcribe_serializes_with_lock(self) -> None:
        """Concurrent transcribe calls must not overlap (GPU safety)."""
        from video_processor.stt_whisper import WhisperEngine

        model = MagicMock()
        order: list[str] = []

        def _transcribe(*_a: Any, **_k: Any) -> Any:
            order.append("start")
            order.append("end")
            return ([], MagicMock())

        model.transcribe.side_effect = _transcribe
        engine = WhisperEngine(model, language=None)

        import threading

        threads = [threading.Thread(target=engine.transcribe, args=(Path("c.wav"),)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each call fully completes (start,end) before the next begins.
        assert order == ["start", "end"] * 4


class TestWhisperCudaFallback:
    def test_falls_back_to_cpu_when_cuda_libs_missing(self) -> None:
        from video_processor.stt_whisper import _build_whisper_model

        calls: list[tuple[str, str]] = []

        class FakeModel:
            def __init__(self, model: str, device: str, compute_type: str) -> None:
                calls.append((device, compute_type))
                if device == "cuda":
                    raise OSError("libcublas.so.12: cannot open shared object file")

        cfg = _cfg(stt_engine="whisper", whisper_device="cuda", whisper_model="small")
        with pytest.warns(UserWarning, match="falling back to CPU"):
            _model, device = _build_whisper_model(FakeModel, cfg, "cuda", fallback=True)

        assert device == "cpu"
        assert calls == [("cuda", "float16"), ("cpu", "int8")]

    def test_no_fallback_when_cpu_fails(self) -> None:
        from video_processor.stt_whisper import _build_whisper_model

        class FakeModel:
            def __init__(self, *_a: Any, **_k: Any) -> None:
                raise OSError("unrelated failure")

        cfg = _cfg(stt_engine="whisper", whisper_device="cpu", whisper_model="small")
        with pytest.raises(OSError):
            _build_whisper_model(FakeModel, cfg, "cpu", fallback=True)

    def test_cuda_success_does_not_fall_back(self) -> None:
        from video_processor.stt_whisper import _build_whisper_model

        class FakeModel:
            def __init__(self, model: str, device: str, compute_type: str) -> None:
                self.device = device

        cfg = _cfg(stt_engine="whisper", whisper_device="cuda", whisper_model="small")
        _model, device = _build_whisper_model(FakeModel, cfg, "cuda", fallback=True)
        assert device == "cuda"


def _install_fake_faster_whisper() -> Any:
    """Inject a fake faster_whisper module with a mock WhisperModel."""
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = MagicMock()  # type: ignore[attr-defined]
    sys.modules["faster_whisper"] = module
    return module
