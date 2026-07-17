"""faster-whisper speech-to-text engine adapter (CTranslate2 backend)."""

from __future__ import annotations

import threading
import warnings
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

from .errors import PipelineError, ProcessCancelledError
from .transcribe import WordInfo

if TYPE_CHECKING:
    from .config import PipelineConfig


def _detect_device(device: str) -> str:
    """Resolve ``auto`` to ``cuda`` (if available) or ``cpu``."""
    if device != "auto":
        return device
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except ImportError:
        # ctranslate2 ships with faster-whisper; if missing, fall back to CPU.
        pass
    return "cpu"


def _default_compute_type(device: str) -> str:
    """Pick a sensible compute type for the resolved device."""
    return "float16" if device == "cuda" else "int8"


def _preload_cuda_libraries() -> None:
    """Preload pip-installed CUDA shared libraries by absolute path.

    ctranslate2 opens ``libcublas``/``libcudnn`` by soname, but the
    ``nvidia-cublas-cu12`` / ``nvidia-cudnn-cu12`` pip packages install them
    under ``site-packages/nvidia/*/lib``, which is not on the dynamic linker
    search path. Loading them with their absolute path makes them resident in
    the process so subsequent soname lookups succeed — both during model
    construction and during transcription.
    """
    import ctypes
    import importlib.util
    import os

    # soname -> the nvidia package that ships it.
    candidates = [
        ("libcublas.so.12", "nvidia.cublas"),
        ("libcudnn.so.9", "nvidia.cudnn"),
    ]
    for soname, pkg in candidates:
        try:
            spec = importlib.util.find_spec(pkg)
        except (ImportError, ModuleNotFoundError):
            continue
        if spec is None or not spec.submodule_search_locations:
            continue
        lib_dir = os.path.join(spec.submodule_search_locations[0], "lib")
        full_path = os.path.join(lib_dir, soname)
        if os.path.exists(full_path):
            try:
                ctypes.CDLL(full_path)
            except OSError:
                pass


def _build_whisper_model(
    whisper_cls: Any,
    config: PipelineConfig,
    device: str,
    *,
    fallback: bool,
) -> tuple[Any, str]:
    """Instantiate a WhisperModel, falling back to CPU if CUDA libs are missing.

    ``ctranslate2.get_cuda_device_count`` only checks the driver, so a machine
    can report a CUDA device yet fail to load ``libcublas``/``cuDNN``. To avoid
    a hard crash we retry on CPU and warn the user how to enable GPU.
    """
    if device == "cuda":
        _preload_cuda_libraries()
    compute_type = config.whisper_compute_type or _default_compute_type(device)
    try:
        model = whisper_cls(
            config.whisper_model,
            device=device,
            compute_type=compute_type,
        )
        return model, device
    except (OSError, RuntimeError) as exc:
        if not fallback or device != "cuda":
            raise
        warnings.warn(
            f"CUDA is unavailable ({exc}); falling back to CPU. To enable GPU, "
            "install the CUDA runtime libraries:\n"
            "    pip install nvidia-cublas-cu12 nvidia-cudnn-cu12",
            stacklevel=3,
        )
        device = "cpu"
        compute_type = config.whisper_compute_type or _default_compute_type(device)
        model = whisper_cls(
            config.whisper_model,
            device=device,
            compute_type=compute_type,
        )
        return model, device


class WhisperEngine:
    """Speech-to-text engine backed by faster-whisper.

    faster-whisper runs on a single accelerator (CPU or one GPU). Transcription
    calls are serialized with a lock so that, when used from the parallel
    pipeline, the GPU is fed one job at a time while other workers keep
    encoding already-transcribed segments. This naturally overlaps the
    transcription bottleneck with FFmpeg rendering.
    """

    def __init__(
        self,
        model: Any,
        language: str | None,
        *,
        device: str | None = None,
        cpu_model_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._model = model
        self._language = language
        self._device = device
        self._cpu_model_factory = cpu_model_factory
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config: PipelineConfig) -> WhisperEngine:
        """Build a WhisperEngine from pipeline configuration.

        If CUDA is selected but the CUDA runtime libraries (libcublas, cuDNN)
        are missing, transparently fall back to CPU so the pipeline keeps working
        instead of crashing.
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise PipelineError(
                'faster-whisper is not installed. Install it with: pip install -e ".[stt]"'
            ) from exc

        device = _detect_device(config.whisper_device)
        model, device = _build_whisper_model(WhisperModel, config, device, fallback=True)

        def cpu_model_factory() -> Any:
            return _build_whisper_model(WhisperModel, config, "cpu", fallback=False)[0]

        return cls(
            model,
            config.language,
            device=device,
            cpu_model_factory=cpu_model_factory if device == "cuda" else None,
        )

    def _run_transcription(self, wav_path: Path, cancel_event: Event | None) -> list[Any]:
        segments, _info = self._model.transcribe(
            str(wav_path),
            language=self._language,
            word_timestamps=True,
            vad_filter=True,
        )
        # faster-whisper transcription is lazy: CUDA errors often surface here.
        result: list[Any] = []
        for segment in segments:
            if cancel_event is not None and cancel_event.is_set():
                raise ProcessCancelledError("Speech recognition cancelled")
            result.append(segment)
        return result

    def transcribe(self, wav_path: Path) -> list[WordInfo]:
        return self._transcribe(wav_path, None)

    def transcribe_cancellable(self, wav_path: Path, cancel_event: Event) -> list[WordInfo]:
        return self._transcribe(wav_path, cancel_event)

    def _transcribe(self, wav_path: Path, cancel_event: Event | None) -> list[WordInfo]:
        """Transcribe a WAV file and return word-level timings.

        ``word_timestamps=True`` gives per-word start/end which maps directly to
        :class:`WordInfo`.
        """
        with self._lock:
            if cancel_event is not None and cancel_event.is_set():
                raise ProcessCancelledError("Speech recognition cancelled")
            try:
                segments = self._run_transcription(wav_path, cancel_event)
            except (OSError, RuntimeError) as exc:
                if self._device != "cuda" or self._cpu_model_factory is None:
                    raise
                warnings.warn(
                    f"CUDA inference failed ({exc}); falling back to CPU.",
                    stacklevel=2,
                )
                self._model = self._cpu_model_factory()
                self._device = "cpu"
                self._cpu_model_factory = None
                segments = self._run_transcription(wav_path, cancel_event)

        words: list[WordInfo] = []
        for segment in segments:
            for word in segment.words or []:
                words.append(
                    WordInfo(
                        word=word.word.strip(),
                        start=word.start,
                        end=word.end,
                    )
                )
        return words
