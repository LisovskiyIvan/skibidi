"""ASS subtitle generation and time formatting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import PipelineConfig

if TYPE_CHECKING:
    from .transcribe import Cue


def ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.cc."""
    centis = int(round(seconds * 100))
    h = centis // 360000
    centis %= 360000
    m = centis // 6000
    centis %= 6000
    s = centis // 100
    centis %= 100
    return f"{h}:{m:02d}:{s:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    """Escape ASS special characters that could be interpreted as override tags."""
    return text.replace("{", "\\{").replace("}", "\\}")


def build_ass_header(config: PipelineConfig) -> list[str]:
    """Build the ASS script header and default style as a list of lines."""
    return [
        "[Script Info]",
        "Title: Auto-generated subtitles",
        "ScriptType: v4.00+",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{config.subtitle_font},{config.subtitle_fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,0,2,40,40,420,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


def generate_ass(config: PipelineConfig, cues: list[Cue]) -> str:
    """Generate an ASS subtitle file from grouped cues."""
    lines = build_ass_header(config)
    for cue in cues:
        start = ass_time(cue["start"])
        end = ass_time(cue["end"])
        text = _escape_ass_text(cue["text"])
        # Center horizontally at x=540, vertically at the configured Y position.
        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,"
            f"{{\\pos(540,{config.subtitle_pos_y})\\fad({config.fade_in_ms},{config.fade_out_ms})}}"
            f"{text}"
        )
    return "\n".join(lines) + "\n"
