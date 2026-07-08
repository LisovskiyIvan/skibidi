"""Speech-to-text using Vosk and word grouping into subtitle cues."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any, TypedDict

from vosk import KaldiRecognizer, Model


class WordInfo(TypedDict):
    word: str
    start: float
    end: float


class Cue(TypedDict):
    start: float
    end: float
    text: str


def load_model(model_dir: Path) -> Model:
    """Load a Vosk model from disk."""
    return Model(str(model_dir))


def transcribe_words(model: Model, wav_path: Path) -> list[WordInfo]:
    """Transcribe a 16kHz mono WAV file and return timed words."""
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

        recognizer = KaldiRecognizer(model, wf.getframerate())
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


def transcribe_to_cues(model: Model, wav_path: Path) -> list[Cue]:
    """High-level helper: transcribe a WAV file and return grouped cues."""
    words = transcribe_words(model, wav_path)
    return group_words_into_cues(words)
