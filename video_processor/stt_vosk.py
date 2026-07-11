"""Vosk speech-to-text engine adapter."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

from vosk import KaldiRecognizer, Model

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
        """Transcribe a 16kHz mono 16-bit PCM WAV file and return timed words."""
        wf = wave.open(str(wav_path), "rb")
        with wf:
            if (
                wf.getnchannels() != 1
                or wf.getsampwidth() != 2
                or wf.getframerate() != 16000
            ):
                raise ValueError(
                    "WAV must be mono 16-bit PCM @16kHz. (Use the extract_wav step)"
                )

            recognizer = KaldiRecognizer(self._model, wf.getframerate())
            recognizer.SetWords(True)

            results: list[dict[str, Any]] = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if recognizer.AcceptWaveform(data):
                    results.append(json.loads(recognizer.Result()))
            results.append(json.loads(recognizer.FinalResult()))

        words: list[WordInfo] = []
        for result in results:
            for word in result.get("result", []):
                words.append(
                    WordInfo(
                        word=word["word"],
                        start=word["start"],
                        end=word["end"],
                    )
                )
        return words
