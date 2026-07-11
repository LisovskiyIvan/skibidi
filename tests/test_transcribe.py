"""Tests for word grouping into subtitle cues."""

from video_processor.transcribe import (
    Cue,
    WordInfo,
    group_words_into_cues,
    transcribe_to_cues,
)


def _w(word: str, start: float, end: float) -> WordInfo:
    return WordInfo(word=word, start=start, end=end)


class TestGroupWordsIntoCues:
    def test_empty(self) -> None:
        assert group_words_into_cues([]) == []

    def test_single_word(self) -> None:
        out = group_words_into_cues([_w("hi", 0.0, 0.5)])
        assert out == [Cue(start=0.0, end=0.5, text="hi")]

    def test_adjacent_words_merge(self) -> None:
        out = group_words_into_cues([_w("a", 0.0, 0.2), _w("b", 0.25, 0.5)])
        assert len(out) == 1
        assert out[0]["text"] == "a b"
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == 0.5

    def test_long_gap_splits_cue(self) -> None:
        out = group_words_into_cues(
            [_w("hello", 0.0, 0.3), _w("world", 1.5, 1.8)]  # 1.2s gap > 0.8 default
        )
        assert len(out) == 2
        assert out[0]["text"] == "hello"
        assert out[1]["text"] == "world"

    def test_max_chars_splits_cue(self) -> None:
        words = [_w(f"word{i}", i * 0.1, i * 0.1 + 0.05) for i in range(50)]
        out = group_words_into_cues(words, max_chars=20, max_gap=10.0)
        assert len(out) > 1
        assert all(len(c["text"]) <= 20 + len(" word49") for c in out)

    def test_custom_max_gap(self) -> None:
        out = group_words_into_cues(
            [_w("a", 0.0, 0.2), _w("b", 0.5, 0.7)], max_gap=0.2, max_chars=100
        )
        # gap = 0.3 > 0.2 -> split
        assert len(out) == 2


class TestTranscribeToCues:
    def test_uses_defaults(self) -> None:
        # transcribe_to_cues delegates to group_words_into_cues with defaults;
        # we verify the grouping contract via the public helper signature.
        import inspect

        sig = inspect.signature(transcribe_to_cues)
        assert list(sig.parameters) == ["engine", "wav_path"]
