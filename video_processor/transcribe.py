"""Speech-to-text engine abstraction and subtitle cue grouping.

The pipeline talks to any STT engine through the :class:`SpeechToText` protocol,
which produces timed words (:class:`WordInfo`). Engine-specific adapters live in
:mod:`video_processor.stt_vosk` and :mod:`video_processor.stt_whisper` and are
loaded lazily by :func:`create_stt_engine`. Word grouping into subtitle cues is
engine-agnostic and lives here.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from .config import PipelineConfig


class WordInfo(TypedDict):
    word: str
    start: float
    end: float


class Cue(TypedDict):
    start: float
    end: float
    text: str


@runtime_checkable
class SpeechToText(Protocol):
    """A speech-to-text engine that produces timed words from a WAV file."""

    def transcribe(self, wav_path: Path) -> list[WordInfo]:
        """Transcribe ``wav_path`` and return word-level timings."""
        ...


def group_words_into_cues(
    words: list[WordInfo],
    max_chars: int = 60,
    max_gap: float = 0.8,
) -> list[Cue]:
    """Group individual words into subtitle cues by gap and line length."""
    if not words:
        return []

    cues: list[Cue] = []
    cur = Cue(start=words[0]["start"], end=words[0]["end"], text=words[0]["word"])
    for word in words[1:]:
        gap = word["start"] - cur["end"]
        next_text = f"{cur['text']} {word['word']}".strip()
        if gap > max_gap or len(next_text) > max_chars:
            cues.append(cur)
            cur = Cue(start=word["start"], end=word["end"], text=word["word"])
        else:
            cur["text"] = next_text
            cur["end"] = word["end"]
    cues.append(cur)
    return cues


def transcribe_to_cues(engine: SpeechToText, wav_path: Path) -> list[Cue]:
    """High-level helper: transcribe a WAV file and return grouped cues."""
    words = engine.transcribe(wav_path)
    return group_words_into_cues(words)


def transcribe_to_cues_cancellable(
    engine: SpeechToText,
    wav_path: Path,
    cancel_event: Event,
) -> list[Cue]:
    """Transcribe with cancellation when supported by the selected adapter."""
    cancellable = getattr(engine, "transcribe_cancellable", None)
    words = (
        cancellable(wav_path, cancel_event)
        if callable(cancellable)
        else engine.transcribe(wav_path)
    )
    return group_words_into_cues(words)


def create_stt_engine(config: PipelineConfig) -> SpeechToText:
    """Create the speech-to-text engine selected by ``config.stt_engine``.

    Engine modules are imported lazily so the heavy optional dependencies
    (e.g. ``faster-whisper``) are only required when actually used.
    """
    from .errors import PipelineError

    engine = config.stt_engine.lower()
    if engine == "vosk":
        from .stt_vosk import VoskEngine

        return VoskEngine(config.model_dir)
    if engine == "whisper":
        from .stt_whisper import WhisperEngine

        return WhisperEngine.from_config(config)
    raise PipelineError(f"Unknown STT engine: {config.stt_engine!r}. Use 'vosk' or 'whisper'.")
