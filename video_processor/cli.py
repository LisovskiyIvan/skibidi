"""Command-line interface for the video transcription pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import PipelineConfig
from .errors import PipelineError
from .pipeline import run_pipeline
from .progress import ProgressCallback, Step, default_message
from .resources import (
    get_default_credentials_path,
    get_default_font_path,
    get_default_model_dir,
    get_default_token_path,
)
from .youtube import upload_to_youtube
from .youtube_config import YouTubeUploadConfig


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
        "--seed",
        type=int,
        default=None,
        help="Seed for randomized effects such as a speed range (default: random).",
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
    # YouTube upload options
    parser.add_argument(
        "--upload",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Upload the rendered final clips to YouTube after processing.",
    )
    parser.add_argument(
        "--upload-only",
        type=Path,
        default=None,
        help="Upload a single file or every video in a directory without running the pipeline.",
    )
    parser.add_argument(
        "--yt-credentials",
        type=Path,
        default=get_default_credentials_path(),
        help="Path to the OAuth client_secret.json file (default: user config dir).",
    )
    parser.add_argument(
        "--yt-token",
        type=Path,
        default=get_default_token_path(),
        help="Path to the cached OAuth token.json file (default: user config dir).",
    )
    parser.add_argument(
        "--yt-title",
        type=str,
        default="{name}",
        help="Video title template; supports {name}, {idx}, {total} (default: {name}).",
    )
    parser.add_argument(
        "--yt-description",
        type=str,
        default="",
        help="YouTube video description.",
    )
    parser.add_argument(
        "--yt-tags",
        type=str,
        default=None,
        help="Comma-separated video tags (e.g. 'tag1,tag2').",
    )
    parser.add_argument(
        "--yt-privacy",
        type=str,
        default="private",
        choices=["private", "unlisted", "public"],
        help="Video privacy status (default: private).",
    )
    parser.add_argument(
        "--yt-category",
        type=str,
        default="22",
        help="YouTube category id (default: 22 - People & Blogs).",
    )
    parser.add_argument(
        "--yt-notify",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Notify subscribers about new uploads (default: false).",
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
        seed=args.seed,
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


def youtube_config_from_args(
    args: argparse.Namespace, video_paths: list[Path]
) -> YouTubeUploadConfig:
    tags: list[str] = []
    if args.yt_tags:
        tags = [tag.strip() for tag in args.yt_tags.split(",") if tag.strip()]
    return YouTubeUploadConfig(
        video_paths=video_paths,
        credentials_path=args.yt_credentials,
        token_path=args.yt_token,
        title=args.yt_title,
        description=args.yt_description,
        tags=tags,
        category_id=args.yt_category,
        privacy_status=args.yt_privacy,
        notify_subscribers=args.yt_notify,
    )


def _collect_upload_paths(pipeline_config: PipelineConfig) -> list[Path]:
    """Collect rendered final clips from the pipeline output directory."""
    final_dir = pipeline_config.output_dir / "final"
    if not final_dir.exists():
        return []
    # Prefer subtitled files; fall back to plain clips if subtitles are disabled.
    if pipeline_config.burn_subs:
        clips = sorted(final_dir.glob("clip_*_sub.mp4"))
    else:
        clips = sorted(final_dir.glob("clip_*.mp4"))
        clips = [p for p in clips if not p.name.endswith("_sub.mp4")]
    return clips


def _do_upload(
    config: YouTubeUploadConfig,
    progress: ProgressCallback,
) -> list[str]:
    """Run upload and print the resulting video URLs to stdout."""
    video_ids = upload_to_youtube(config, progress)
    print("YouTube upload complete:")
    for video_id in video_ids:
        print(f"  https://youtu.be/{video_id}")
    return video_ids


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.upload_only:
        if args.input:
            parser.error("--upload-only cannot be combined with -i/--input")
        upload_path: Path = args.upload_only
        if upload_path.is_dir():
            video_paths = sorted(upload_path.glob("*.mp4"))
        else:
            video_paths = [upload_path]
        if not video_paths:
            print("Error: no .mp4 files found for upload.", file=sys.stderr)
            return 1
        yt_config = youtube_config_from_args(args, video_paths)
        try:
            _do_upload(yt_config, _create_progress_callback())
        except PipelineError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"Unexpected error: {exc}", file=sys.stderr)
            return 1
        return 0

    if not args.input:
        parser.error("the following arguments are required: -i/--input")

    config = config_from_args(args)
    try:
        run_pipeline(config, _create_progress_callback())
        if args.upload:
            upload_paths = _collect_upload_paths(config)
            if not upload_paths:
                print(
                    "Warning: --upload requested but no final clips were found.",
                    file=sys.stderr,
                )
                return 0
            yt_config = youtube_config_from_args(args, upload_paths)
            _do_upload(yt_config, _create_progress_callback())
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
