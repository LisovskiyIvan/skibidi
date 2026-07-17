"""Small end-to-end checks against the installed FFmpeg executables."""

from __future__ import annotations

import random
import shutil
import subprocess
from pathlib import Path

import pytest

from video_processor.config import PipelineConfig
from video_processor.ffmpeg import burn_subs, probe_media
from video_processor.subtitles import generate_ass

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

pytestmark = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="FFmpeg integration executables are unavailable",
)


def test_silent_video_special_filters_and_atomic_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input [comma, apostrophe's].mp4"
    output_path = tmp_path / "output [final].mp4"
    ass_path = tmp_path / "captions [source].ass"
    subprocess.run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x90:r=10",
            "-t",
            "0.3",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(input_path),
        ],
        check=True,
    )
    config = PipelineConfig(
        input=input_path,
        output_dir=tmp_path / "out",
        burn_subs=True,
        mirror=False,
        speed="1.0",
        overlay_text="quote ' colon: comma, percent% newline\ntext",
        subtitle_font_path=None,
        video_encoder="libx264",
        hwaccel="none",
        encoder_preset="ultrafast",
        crf=35,
        workers=1,
        encoder_threads=1,
        ffmpeg=str(FFMPEG),
        ffprobe=str(FFPROBE),
    )
    ass_path.write_text(generate_ass(config, []), encoding="utf-8")

    burn_subs(
        config,
        input_path,
        ass_path,
        output_path,
        rng=random.Random(1),
        has_audio=False,
    )

    probe = probe_media(config, output_path)
    assert probe.has_video
    assert not probe.has_audio
    assert not output_path.with_name("output [final].part.mp4").exists()
