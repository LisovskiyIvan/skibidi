"""Focused tests for GUI-independent UI preparation helpers."""

from pathlib import Path

import pytest

from video_processor.config import PipelineConfig
from video_processor.errors import PipelineError
from video_processor.ui import parse_download_urls, validate_pipeline_input


def test_parse_download_urls_strips_blank_lines() -> None:
    assert parse_download_urls(" first \n\nsecond\n") == ["first", "second"]


def test_validate_pipeline_input_runs_before_work(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    validate_pipeline_input(PipelineConfig(input=video, stt_engine="whisper"))

    with pytest.raises(PipelineError, match="Missing input video"):
        validate_pipeline_input(PipelineConfig(input=tmp_path / "missing.mp4"))
