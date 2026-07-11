"""Tests for ASS subtitle generation."""

from pathlib import Path
from typing import Any

from video_processor.config import PipelineConfig
from video_processor.subtitles import (
    _escape_ass_text,
    ass_time,
    build_ass_header,
    generate_ass,
)
from video_processor.transcribe import Cue


def _config(**overrides: Any) -> PipelineConfig:
    base: dict[str, Any] = {"input": Path("dummy.mp4")}
    base.update(overrides)
    return PipelineConfig(**base)


class TestAssTime:
    def test_zero(self) -> None:
        assert ass_time(0.0) == "0:00:00.00"

    def test_rounds_to_centiseconds(self) -> None:
        # 1.236s -> 1:00:01.24 (centiseconds round-half-up via round())
        assert ass_time(1.236) == "0:00:01.24"

    def test_minutes_and_hours(self) -> None:
        assert ass_time(3661.5) == "1:01:01.50"

    def test_just_under_an_hour_rounds_up(self) -> None:
        # 3599.999s -> 359999.9 centiseconds -> rounds to 360000 -> 1:00:00.00
        assert ass_time(3599.999) == "1:00:00.00"


class TestEscapeAssText:
    def test_plain_text_unchanged(self) -> None:
        assert _escape_ass_text("hello world") == "hello world"

    def test_braces_escaped(self) -> None:
        assert _escape_ass_text("{pos}") == "\\{pos\\}"

    def test_empty(self) -> None:
        assert _escape_ass_text("") == ""


class TestBuildAssHeader:
    def test_contains_required_sections(self) -> None:
        header = build_ass_header(_config())
        joined = "\n".join(header)
        assert "[Script Info]" in joined
        assert "[V4+ Styles]" in joined
        assert "[Events]" in joined

    def test_uses_configured_font(self) -> None:
        header = build_ass_header(_config(subtitle_font="MyFont", subtitle_fontsize=42))
        style_line = next(line for line in header if line.startswith("Style: Default"))
        assert "MyFont" in style_line
        assert ",42," in style_line

    def test_includes_play_resolution(self) -> None:
        header = build_ass_header(_config())
        joined = "\n".join(header)
        assert "PlayResX: 1080" in joined
        assert "PlayResY: 1920" in joined


class TestGenerateAss:
    def test_empty_cues_produces_only_header(self) -> None:
        out = generate_ass(_config(), [])
        assert "Dialogue:" not in out
        assert out.endswith("\n")

    def test_cue_lines_have_pos_and_fade(self) -> None:
        cues: list[Cue] = [{"start": 1.0, "end": 2.5, "text": "hi there"}]
        out = generate_ass(_config(subtitle_pos_y=1234, fade_in_ms=150, fade_out_ms=250), cues)
        assert "Dialogue: 0," in out
        assert "\\pos(540,1234)" in out
        assert "\\fad(150,250)" in out
        assert "hi there" in out

    def test_cue_text_is_escaped(self) -> None:
        cues: list[Cue] = [{"start": 0.0, "end": 1.0, "text": "{bad}"}]
        out = generate_ass(_config(), cues)
        assert "\\{bad\\}" in out

    def test_cue_line_field_count_matches_format(self) -> None:
        cues: list[Cue] = [{"start": 1.0, "end": 2.5, "text": "hi there"}]
        out = generate_ass(_config(), cues)
        lines = out.splitlines()
        events_idx = lines.index("[Events]")
        format_line = next(
            line for line in lines[events_idx:] if line.startswith("Format: Layer, Start, End")
        )
        dialogue_line = next(
            line for line in lines[events_idx:] if line.startswith("Dialogue:")
        )
        # Count commas only in the field prefix, before the override block starts with '{'.
        dialogue_prefix = dialogue_line.split("{", 1)[0]
        assert format_line.count(",") == dialogue_prefix.count(",")
        assert dialogue_prefix.count(",") == 9
