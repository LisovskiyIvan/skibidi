"""Command-line interface for the video transcription pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import PipelineConfig
from .pipeline import PipelineError, run_pipeline
from .progress import ProgressCallback, Step, default_message
from .resources import get_default_font_path, get_default_model_dir


def _create_progress_callback() -> ProgressCallback:
    def callback(step: Step, current: int, total: int, message: str) -> None:
        print(default_message(step, current, total, message))
    return callback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-processor",
        description="Split video into segments, transcribe speech with Vosk, "
        "optionally burn subtitles and convert to 9:16.",
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        help="Input video file (required in CLI mode; omit to launch GUI).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("out"),
        help="Output directory (default: ./out).",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=Path,
        default=get_default_model_dir(),
        help="Path to the Vosk model directory (default: ./vosk-model-small-ru-0.22).",
    )
    parser.add_argument(
        "--seg-seconds",
        type=int,
        default=60,
        help="Segment duration in seconds (default: 60).",
    )
    parser.add_argument(
        "--burn-subs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Burn subtitles into the output video (default: true).",
    )
    parser.add_argument(
        "--font",
        type=str,
        default="Oswald",
        help="Font name used in subtitles (default: Oswald).",
    )
    parser.add_argument(
        "--font-path",
        type=Path,
        default=get_default_font_path(),
        help="Path to the font file. Used only to locate fonts for the bundled executable.",
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=100,
        help="Subtitle font size (default: 100).",
    )
    parser.add_argument(
        "--pos-y",
        type=int,
        default=1500,
        help="Vertical subtitle position for 9:16 output (default: 1500).",
    )
    parser.add_argument(
        "--fade-in",
        type=int,
        default=200,
        help="Subtitle fade-in duration in milliseconds (default: 200).",
    )
    parser.add_argument(
        "--fade-out",
        type=int,
        default=200,
        help="Subtitle fade-out duration in milliseconds (default: 200).",
    )
    # Editing / fingerprint-evasion options
    parser.add_argument(
        "--mirror",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mirror the video horizontally (default: true).",
    )
    parser.add_argument(
        "--speed",
        type=str,
        default="0.95-1.05",
        help="Speed factor or range, e.g. 1.0 or 0.95-1.05 (default: 0.95-1.05).",
    )
    parser.add_argument(
        "--brightness",
        type=float,
        default=None,
        help="Brightness adjustment (FFmpeg eq).",
    )
    parser.add_argument(
        "--contrast",
        type=float,
        default=None,
        help="Contrast adjustment (FFmpeg eq).",
    )
    parser.add_argument(
        "--saturation",
        type=float,
        default=None,
        help="Saturation adjustment (FFmpeg eq).",
    )
    parser.add_argument(
        "--gamma",
        type=float,
        default=None,
        help="Gamma adjustment (FFmpeg eq).",
    )
    parser.add_argument(
        "--hue",
        type=float,
        default=None,
        help="Hue adjustment (FFmpeg eq).",
    )
    parser.add_argument(
        "--sharpness",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Apply subtle sharpening (default: false).",
    )
    parser.add_argument(
        "--noise",
        type=int,
        default=0,
        help="Adversarial noise intensity (0 = off).",
    )
    parser.add_argument(
        "--overlay-text",
        type=str,
        default=None,
        help="Text overlay drawn at the bottom center.",
    )
    parser.add_argument(
        "--bg-audio",
        type=Path,
        default=None,
        help="Optional background audio file mixed with the original audio.",
    )
    parser.add_argument(
        "--bg-volume",
        type=float,
        default=0.3,
        help="Background audio volume (default: 0.3).",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> PipelineConfig:
    return PipelineConfig(
        input=args.input,
        output_dir=args.output,
        model_dir=args.model,
        seg_seconds=args.seg_seconds,
        burn_subs=args.burn_subs,
        subtitle_font=args.font,
        subtitle_font_path=args.font_path,
        subtitle_fontsize=args.font_size,
        subtitle_pos_y=args.pos_y,
        fade_in_ms=args.fade_in,
        fade_out_ms=args.fade_out,
        mirror=args.mirror,
        speed=args.speed,
        brightness=args.brightness,
        contrast=args.contrast,
        saturation=args.saturation,
        gamma=args.gamma,
        hue=args.hue,
        sharpness=args.sharpness,
        noise=args.noise,
        overlay_text=args.overlay_text,
        background_audio=args.bg_audio,
        background_audio_volume=args.bg_volume,
    )


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.input:
        parser.error("the following arguments are required: -i/--input")

    config = config_from_args(args)
    try:
        run_pipeline(config, _create_progress_callback())
    except PipelineError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    """Entry point that switches between CLI and GUI based on arguments."""
    # If there are no user arguments, launch the GUI. Otherwise run the CLI.
    if len(sys.argv) == 1:
        from .ui import run_gui
        return run_gui()
    return run_cli()
