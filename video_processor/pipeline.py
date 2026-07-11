"""High-level pipeline that ties together all core operations."""

from __future__ import annotations

import concurrent.futures
import math
import random
import threading
from collections.abc import Callable
from pathlib import Path

from vosk import Model

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
    progress_lock: threading.Lock,
    step: Step,
    idx: int,
    total: int,
    label: str,
    duration: float,
) -> Callable[[str], None]:
    """Return an FFmpeg stderr-line callback that reports throttled percent.

    Percent is bucketed to 5% steps so the CLI output stays readable while the
    GUI still gets smooth-enough updates. The callback is thread-safe via the
    supplied lock.
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
        with progress_lock:
            progress(step, idx, total, f"{label} {pct:.0f}%")

    return cb


def _segment_paths(config: PipelineConfig, idx: int) -> tuple[Path, Path, Path, Path]:
    """Return (segment_path, wav_path, ass_path, final_path) for a segment index."""
    segment_path = config.output_dir / "segments" / f"clip_{idx:02d}.mp4"
    wav_path = config.output_dir / "wav" / f"clip_{idx:02d}.wav"
    ass_path = config.output_dir / "srt" / f"clip_{idx:02d}.ass"
    final_name = f"clip_{idx:02d}_sub.mp4" if config.burn_subs else f"clip_{idx:02d}.mp4"
    final_path = config.output_dir / "final" / final_name
    return segment_path, wav_path, ass_path, final_path


def _segment_rng(config: PipelineConfig, idx: int) -> random.Random:
    """Return a deterministic Random for the segment, preserving ``--seed``."""
    base = config.seed if config.seed is not None else random.randrange(2**31)
    return random.Random(base ^ idx)


def _process_segment(
    config: PipelineConfig,
    model: Model,
    idx: int,
    total_segments: int,
    progress_lock: threading.Lock,
    progress: ProgressCallback,
) -> None:
    """Process a single segment: extract, transcribe, generate ASS, render."""
    start = idx * config.seg_seconds
    segment_path, wav_path, ass_path, final_path = _segment_paths(config, idx)

    # Resume support: skip segments that already have a rendered output.
    if final_path.exists():
        with progress_lock:
            progress(
                Step.SEGMENT,
                idx,
                total_segments,
                f"skip existing {final_path.name}",
            )
        return

    with progress_lock:
        progress(
            Step.SEGMENT,
            idx,
            total_segments,
            f"segment {start}-{start + config.seg_seconds}s -> {segment_path.name}",
        )
    extract_segment(config, config.input, start, config.seg_seconds, segment_path)

    with progress_lock:
        progress(
            Step.TRANSCRIBE,
            idx,
            total_segments,
            f"extracting WAV and recognizing speech for {segment_path.name}",
        )
    extract_wav(config, segment_path, wav_path)
    cues = transcribe_to_cues(model, wav_path)
    ass_path.write_text(generate_ass(config, cues), encoding="utf-8")

    rng = _segment_rng(config, idx)
    if config.burn_subs:
        with progress_lock:
            progress(
                Step.BURN,
                idx,
                total_segments,
                f"burning subtitles into {final_path.name}",
            )
        line_cb = _make_progress_line_cb(
            progress,
            progress_lock,
            Step.BURN,
            idx,
            total_segments,
            f"burning {final_path.name}",
            float(config.seg_seconds),
        )
        burn_subs(
            config, segment_path, ass_path, final_path, rng=rng, on_line=line_cb
        )
    else:
        with progress_lock:
            progress(
                Step.CONVERT,
                idx,
                total_segments,
                f"converting to 9:16 without subtitles -> {final_path.name}",
            )
        line_cb = _make_progress_line_cb(
            progress,
            progress_lock,
            Step.CONVERT,
            idx,
            total_segments,
            f"converting {final_path.name}",
            float(config.seg_seconds),
        )
        convert_to_9x16(
            config, segment_path, final_path, rng=rng, on_line=line_cb
        )


def run_pipeline(config: PipelineConfig, progress: ProgressCallback = noop_progress) -> None:
    """Run the full video processing pipeline.

    The pipeline is usable directly from Python code, from the CLI, or from the
    GUI by supplying a suitable progress callback. Segments are processed in
    parallel (up to ``config.workers``) to overlap transcription and encoding.
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

    progress(
        Step.SEGMENT,
        0,
        total_segments,
        f"Duration {duration:.2f}s -> {total_segments} segments",
    )

    model = load_model(config.model_dir)
    progress_lock = threading.Lock()

    # Determine which segments still need work (resume support).
    pending: list[int] = []
    for idx in range(total_segments):
        _, _, _, final_path = _segment_paths(config, idx)
        if final_path.exists():
            progress(
                Step.SEGMENT,
                idx,
                total_segments,
                f"skip existing {final_path.name}",
            )
        else:
            pending.append(idx)

    if not pending:
        progress(
            Step.DONE,
            total_segments,
            total_segments,
            f"final videos: {final_dir}; ASS files: {srt_dir}",
        )
        return

    workers = max(1, min(config.workers, len(pending)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _process_segment,
                config,
                model,
                idx,
                total_segments,
                progress_lock,
                progress,
            ): idx
            for idx in pending
        }
        exceptions: list[BaseException] = []
        for future in concurrent.futures.as_completed(futures):
            exc = future.exception()
            if exc is not None:
                exceptions.append(exc)

    if exceptions:
        # Raise the first exception that occurred, preserving its traceback.
        raise exceptions[0]

    progress(
        Step.DONE,
        total_segments,
        total_segments,
        f"final videos: {final_dir}; ASS files: {srt_dir}",
    )
