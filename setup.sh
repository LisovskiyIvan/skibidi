#!/usr/bin/env bash
set -euo pipefail

for tool in uv ffmpeg ffprobe; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Required tool not found: %s\n' "$tool" >&2
        printf 'Install uv from https://docs.astral.sh/uv/ and FFmpeg from your OS package manager.\n' >&2
        exit 1
    fi
done

printf 'uv: %s\n' "$(uv --version)"
ffmpeg_version="$(ffmpeg -version 2>/dev/null)"
printf 'ffmpeg: %s\n' "${ffmpeg_version%%$'\n'*}"

uv sync --locked \
    --extra dev \
    --extra gui

if ! uv run python -c "import tkinter" >/dev/null 2>&1; then
    printf 'Tkinter is unavailable. Install your OS Python Tk package for the GUI.\n' >&2
    exit 1
fi

if [[ ! -d vosk-model-small-ru-0.22 ]]; then
    printf 'Missing tracked Vosk model directory: vosk-model-small-ru-0.22\n' >&2
    exit 1
fi

if [[ ! -f assets/oswald/static/Oswald-Bold.ttf ]]; then
    printf 'Oswald font is absent; subtitles will use the runtime font fallback.\n' >&2
fi

printf 'Setup complete. Run: uv run video-processor --help\n'
