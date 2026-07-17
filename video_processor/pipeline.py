"""High-level pipeline that ties together all core operations."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import random
import threading
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

from .config import PipelineConfig
from .constants import PROGRESS_BUCKET_PERCENT
from .errors import PipelineError, ProcessCancelledError
from .ffmpeg import (
    MediaProbe,
    burn_subs,
    convert_to_9x16,
    extract_wav,
    parse_ffmpeg_seconds,
    probe_media,
)
from .progress import ProgressCallback, Step, noop_progress
from .subtitles import generate_ass
from .transcribe import SpeechToText, create_stt_engine, transcribe_to_cues_cancellable

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
        bucket = int(pct) // PROGRESS_BUCKET_PERCENT * PROGRESS_BUCKET_PERCENT
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


def _path_identity(path: Path) -> dict[str, Any]:
    """Return inexpensive identity data suitable for resume invalidation."""
    resolved = path.expanduser().resolve()
    try:
        stat = resolved.stat()
    except OSError:
        return {"path": str(resolved), "missing": True}
    identity: dict[str, Any] = {
        "path": str(resolved),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "is_dir": resolved.is_dir(),
    }
    if resolved.is_dir():
        identity["entries"] = [
            {
                "path": str(entry.relative_to(resolved).as_posix()),
                "size": entry.stat().st_size,
                "mtime_ns": entry.stat().st_mtime_ns,
            }
            for entry in sorted(resolved.rglob("*"))
            if entry.is_file()
        ]
    return identity


def _fingerprint(config: PipelineConfig) -> str:
    """Fingerprint the input identity and every output-affecting option."""
    operational = {
        "output_dir",
        "ffmpeg_timeout_sec",
        "ffprobe_timeout_sec",
        "stderr_limit",
        "keep_intermediates",
        "cancel_event",
    }
    values: dict[str, Any] = {}
    for item in fields(config):
        if item.name in operational:
            continue
        value = getattr(config, item.name)
        if isinstance(value, Path):
            values[item.name] = _path_identity(value)
        else:
            values[item.name] = value
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _manifest_path(config: PipelineConfig) -> Path:
    return config.output_dir / "final" / "resume-manifest.json"


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _output_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"name": path.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _valid_resumed_output(
    config: PipelineConfig,
    final_path: Path,
    idx: int,
    fingerprint: str,
    manifest: dict[str, Any],
    cancel_event: threading.Event | None = None,
) -> bool:
    if manifest.get("version") != 2 or manifest.get("fingerprint") != fingerprint:
        return False
    segments = manifest.get("segments")
    if not isinstance(segments, dict) or segments.get(str(idx)) is None:
        return False
    try:
        if segments[str(idx)] != _output_identity(final_path):
            return False
        return probe_media(config, final_path, cancel_event=cancel_event).has_video
    except ProcessCancelledError:
        raise
    except (OSError, PipelineError):
        return False


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    part = path.with_name(f"{path.stem}.part{path.suffix}")
    part.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    part.replace(path)


def _process_segment(
    config: PipelineConfig,
    engine: SpeechToText | None,
    media: MediaProbe,
    idx: int,
    total_segments: int,
    progress_lock: threading.Lock,
    progress: ProgressCallback,
    cancel_event: threading.Event,
    on_success: Callable[[int, Path], None],
) -> None:
    """Process a segment directly from the source, then publish it atomically."""
    if cancel_event.is_set():
        raise ProcessCancelledError("Pipeline cancelled")
    start = idx * config.seg_seconds
    segment_path, wav_path, ass_path, final_path = _segment_paths(config, idx)
    segment_duration = min(float(config.seg_seconds), media.duration - start)

    with progress_lock:
        progress(
            Step.SEGMENT,
            idx,
            total_segments,
            f"segment {start}-{start + segment_duration:g}s -> {final_path.name}",
        )

    if engine is not None:
        with progress_lock:
            progress(
                Step.TRANSCRIBE,
                idx,
                total_segments,
                f"extracting WAV and recognizing speech for {final_path.name}",
            )
        extract_wav(
            config,
            config.input,
            wav_path,
            start=start,
            duration=segment_duration,
            cancel_event=cancel_event,
        )
        if cancel_event.is_set():
            raise ProcessCancelledError("Pipeline cancelled")
        cues = transcribe_to_cues_cancellable(engine, wav_path, cancel_event)
    else:
        cues = []
    ass_part_path = ass_path.with_name(f"{ass_path.stem}.part{ass_path.suffix}")

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
            segment_duration,
        )
        try:
            ass_part_path.unlink(missing_ok=True)
            ass_part_path.write_text(generate_ass(config, cues), encoding="utf-8")
            burn_subs(
                config,
                config.input,
                ass_part_path,
                final_path,
                rng=rng,
                on_line=line_cb,
                has_audio=media.has_audio,
                start=start,
                duration=segment_duration,
                cancel_event=cancel_event,
            )
            ass_part_path.replace(ass_path)
        finally:
            ass_part_path.unlink(missing_ok=True)
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
            segment_duration,
        )
        convert_to_9x16(
            config,
            config.input,
            final_path,
            rng=rng,
            on_line=line_cb,
            has_audio=media.has_audio,
            start=start,
            duration=segment_duration,
            cancel_event=cancel_event,
        )
    on_success(idx, final_path)
    if not config.keep_intermediates:
        segment_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)


def run_pipeline(config: PipelineConfig, progress: ProgressCallback = noop_progress) -> None:
    """Run the full video processing pipeline.

    The pipeline is usable directly from Python code, from the CLI, or from the
    GUI by supplying a suitable progress callback. Segments are processed in
    parallel (up to ``config.workers``) to overlap transcription and encoding.
    """
    config.validate()
    cancel_event = config.cancel_event or threading.Event()
    if cancel_event.is_set():
        raise ProcessCancelledError("Pipeline cancelled")
    if not config.input.is_file():
        raise PipelineError(f"Missing input video: {config.input}")
    if config.background_audio is not None and not config.background_audio.is_file():
        raise PipelineError(f"Missing background audio: {config.background_audio}")

    media = probe_media(config, config.input, cancel_event=cancel_event)
    if not media.has_video:
        raise PipelineError(f"Input has no video stream: {config.input}")
    duration = media.duration
    total_segments = int(math.ceil(duration / config.seg_seconds))

    progress(
        Step.SEGMENT,
        0,
        total_segments,
        f"Duration {duration:.2f}s -> {total_segments} segments",
    )

    fingerprint = _fingerprint(config)
    manifest_path = _manifest_path(config)
    manifest = _load_manifest(manifest_path)
    pending: list[int] = []
    for idx in range(total_segments):
        _, _, _, final_path = _segment_paths(config, idx)
        if _valid_resumed_output(config, final_path, idx, fingerprint, manifest, cancel_event):
            progress(
                Step.SEGMENT,
                idx,
                total_segments,
                f"skip existing {final_path.name}",
            )
        else:
            pending.append(idx)

    if not pending:
        final_dir = config.output_dir / "final"
        srt_dir = config.output_dir / "srt"
        progress(
            Step.DONE,
            total_segments,
            total_segments,
            f"final videos: {final_dir}; ASS files: {srt_dir}",
        )
        return

    needs_stt = config.burn_subs and media.has_audio
    if needs_stt and config.stt_engine == "vosk" and not config.model_dir.is_dir():
        raise PipelineError(f"Missing Vosk model directory: {config.model_dir}")

    wav_dir = config.output_dir / "wav"
    srt_dir = config.output_dir / "srt"
    final_dir = config.output_dir / "final"
    for directory in (wav_dir, srt_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)

    engine = create_stt_engine(config) if needs_stt else None
    progress_lock = threading.Lock()
    manifest_lock = threading.Lock()
    if manifest.get("version") != 2 or manifest.get("fingerprint") != fingerprint:
        manifest = {
            "version": 2,
            "fingerprint": fingerprint,
            "total_segments": total_segments,
            "segments": {},
        }
    else:
        manifest["total_segments"] = total_segments
    segments = manifest.setdefault("segments", {})
    if not isinstance(segments, dict):
        segments = {}
        manifest["segments"] = segments

    def record_success(idx: int, final_path: Path) -> None:
        with manifest_lock:
            segments[str(idx)] = _output_identity(final_path)
            _write_manifest(manifest_path, manifest)

    workers = max(1, min(config.workers, len(pending)))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futures = {
        executor.submit(
            _process_segment,
            config,
            engine,
            media,
            idx,
            total_segments,
            progress_lock,
            progress,
            cancel_event,
            record_success,
        ): idx
        for idx in pending
    }
    try:
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            try:
                future.result()
            except Exception as exc:
                cancel_event.set()
                for queued in futures:
                    queued.cancel()
                raise PipelineError(f"Segment {idx} failed: {exc}") from exc
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    progress(
        Step.DONE,
        total_segments,
        total_segments,
        f"final videos: {final_dir}; ASS files: {srt_dir}",
    )
