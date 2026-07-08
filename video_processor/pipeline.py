"""High-level pipeline that ties together all core operations."""

from __future__ import annotations

import math

from .config import PipelineConfig
from .ffmpeg import burn_subs, convert_to_9x16, extract_segment, extract_wav, get_duration_sec
from .progress import ProgressCallback, Step, noop_progress
from .subtitles import generate_ass
from .transcribe import load_model, transcribe_to_cues


class PipelineError(Exception):
    """Raised when a pipeline step fails."""

    pass


def run_pipeline(config: PipelineConfig, progress: ProgressCallback = noop_progress) -> None:
    """Run the full video processing pipeline.

    The pipeline is usable directly from Python code, from the CLI, or from the
    GUI by supplying a suitable progress callback.
    """
    if not config.input.exists():
        raise FileNotFoundError(f"Missing input video: {config.input}")
    if not config.model_dir.exists():
        raise FileNotFoundError(f"Missing Vosk model directory: {config.model_dir}")

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

    for idx in range(total_segments):
        start = idx * config.seg_seconds

        segment_path = segments_dir / f"clip_{idx:02d}.mp4"
        wav_path = wav_dir / f"clip_{idx:02d}.wav"
        ass_path = srt_dir / f"clip_{idx:02d}.ass"

        if config.burn_subs:
            final_path = final_dir / f"clip_{idx:02d}_sub.mp4"
        else:
            final_path = final_dir / f"clip_{idx:02d}.mp4"

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
            burn_subs(config, segment_path, ass_path, final_path)
        else:
            progress(
                Step.CONVERT,
                idx,
                total_segments,
                f"converting to 9:16 without subtitles -> {final_path.name}",
            )
            convert_to_9x16(config, segment_path, final_path)

    progress(
        Step.DONE,
        total_segments,
        total_segments,
        f"final videos: {final_dir}; ASS files: {srt_dir}",
    )
