"""High-level pipeline that ties together all core operations."""

from __future__ import annotations

import math
import random
from collections.abc import Callable

from .config import PipelineConfig
from .errors import PipelineError
from .ffmpeg import (
    burn_subs,
    convert_to_9x16,
    extract_segment,
    extract_wav,
    get_duration_sec,
    parse_ffmpeg_seconds,
)
from .progress import ProgressCallback, Step, noop_progress
from .subtitles import generate_ass
from .transcribe import load_model, transcribe_to_cues

# Re-export so ``from video_processor.pipeline import PipelineError`` still works.
__all__ = ["PipelineError", "run_pipeline"]


def _make_progress_line_cb(
    progress: ProgressCallback,
    step: Step,
    idx: int,
    total: int,
    label: str,
    duration: float,
) -> Callable[[str], None]:
    """Return an FFmpeg stderr-line callback that reports throttled percent.

    Percent is bucketed to 5% steps so the CLI output stays readable while the
    GUI still gets smooth-enough updates.
    """
    state = {"bucket": -1}

    def cb(line: str) -> None:
        seconds = parse_ffmpeg_seconds(line)
        if seconds is None:
            return
        pct = 0 if duration <= 0 else min(seconds / duration * 100.0, 100.0)
        bucket = int(pct) // 5 * 5
        if bucket == state["bucket"]:
            return
        state["bucket"] = bucket
        progress(step, idx, total, f"{label} {pct:.0f}%")

    return cb


def run_pipeline(config: PipelineConfig, progress: ProgressCallback = noop_progress) -> None:
    """Run the full video processing pipeline.

    The pipeline is usable directly from Python code, from the CLI, or from the
    GUI by supplying a suitable progress callback.
    """
    if not config.input.exists():
        raise PipelineError(f"Missing input video: {config.input}")
    if not config.model_dir.exists():
        raise PipelineError(f"Missing Vosk model directory: {config.model_dir}")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    segments_dir = config.output_dir / "segments"
    wav_dir = config.output_dir / "wav"
    srt_dir = config.output_dir / "srt"
    final_dir = config.output_dir / "final"
    for directory in (segments_dir, wav_dir, srt_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)

    duration = get_duration_sec(config, config.input)
    total_segments = int(math.ceil(duration / config.seg_seconds))

    progress(Step.SEGMENT, 0, total_segments, f"Duration {duration:.2f}s -> {total_segments} segments")

    model = load_model(config.model_dir)
    rng = random.Random(config.seed)

    for idx in range(total_segments):
        start = idx * config.seg_seconds

        segment_path = segments_dir / f"clip_{idx:02d}.mp4"
        wav_path = wav_dir / f"clip_{idx:02d}.wav"
        ass_path = srt_dir / f"clip_{idx:02d}.ass"

        if config.burn_subs:
            final_path = final_dir / f"clip_{idx:02d}_sub.mp4"
        else:
            final_path = final_dir / f"clip_{idx:02d}.mp4"

        # Resume support: skip segments that already have a rendered output.
        if final_path.exists():
            progress(
                Step.SEGMENT,
                idx,
                total_segments,
                f"skip existing {final_path.name}",
            )
            continue

        progress(
            Step.SEGMENT,
            idx,
            total_segments,
            f"segment {start}-{start + config.seg_seconds}s -> {segment_path.name}",
        )
        extract_segment(config, config.input, start, config.seg_seconds, segment_path)

        progress(
            Step.TRANSCRIBE,
            idx,
            total_segments,
            f"extracting WAV and recognizing speech for {segment_path.name}",
        )
        extract_wav(config, segment_path, wav_path)
        cues = transcribe_to_cues(model, wav_path)
        ass_path.write_text(generate_ass(config, cues), encoding="utf-8")

        if config.burn_subs:
            progress(
                Step.BURN,
                idx,
                total_segments,
                f"burning subtitles into {final_path.name}",
            )
            line_cb = _make_progress_line_cb(
                progress, Step.BURN, idx, total_segments,
                f"burning {final_path.name}", float(config.seg_seconds),
            )
            burn_subs(
                config, segment_path, ass_path, final_path, rng=rng, on_line=line_cb
            )
        else:
            progress(
                Step.CONVERT,
                idx,
                total_segments,
                f"converting to 9:16 without subtitles -> {final_path.name}",
            )
            line_cb = _make_progress_line_cb(
                progress, Step.CONVERT, idx, total_segments,
                f"converting {final_path.name}", float(config.seg_seconds),
            )
            convert_to_9x16(
                config, segment_path, final_path, rng=rng, on_line=line_cb
            )

    progress(
        Step.DONE,
        total_segments,
        total_segments,
        f"final videos: {final_dir}; ASS files: {srt_dir}",
    )
