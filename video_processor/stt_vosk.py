"""Vosk speech-to-text engine adapter."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from threading import Event
from typing import Any

from vosk import KaldiRecognizer, Model

from .constants import (
    WAV_CHANNELS,
    WAV_READ_FRAMES,
    WAV_SAMPLE_RATE,
    WAV_SAMPLE_WIDTH_BYTES,
)
from .errors import ProcessCancelledError
from .transcribe import WordInfo


class VoskEngine:
    """Speech-to-text engine backed by Vosk (offline Kaldi models).

    The loaded :class:`vosk.Model` is read-only after construction and can be
    shared across threads; each :meth:`transcribe` call builds its own
    ``KaldiRecognizer``, so this engine is safe to use from parallel workers.
    """

    def __init__(self, model_dir: Path) -> None:
        self._model = Model(str(model_dir))

    def transcribe(self, wav_path: Path) -> list[WordInfo]:
        return self._transcribe(wav_path, None)

    def transcribe_cancellable(self, wav_path: Path, cancel_event: Event) -> list[WordInfo]:
        return self._transcribe(wav_path, cancel_event)

    def _transcribe(self, wav_path: Path, cancel_event: Event | None) -> list[WordInfo]:
        """Transcribe a 16kHz mono 16-bit PCM WAV file and return timed words."""
        wf = wave.open(str(wav_path), "rb")
        with wf:
            if (
                wf.getnchannels() != WAV_CHANNELS
                or wf.getsampwidth() != WAV_SAMPLE_WIDTH_BYTES
                or wf.getframerate() != WAV_SAMPLE_RATE
            ):
                raise ValueError("WAV must be mono 16-bit PCM @16kHz. (Use the extract_wav step)")

            recognizer = KaldiRecognizer(self._model, wf.getframerate())
            recognizer.SetWords(True)

            words: list[WordInfo] = []

            def append_words(raw_result: str) -> None:
                result: dict[str, Any] = json.loads(raw_result)
                words.extend(
                    WordInfo(
                        word=word["word"],
                        start=word["start"],
                        end=word["end"],
                    )
                    for word in result.get("result", [])
                )

            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ProcessCancelledError("Speech recognition cancelled")
                data = wf.readframes(WAV_READ_FRAMES)
                if not data:
                    break
                if recognizer.AcceptWaveform(data):
                    append_words(recognizer.Result())
            append_words(recognizer.FinalResult())

        return words
