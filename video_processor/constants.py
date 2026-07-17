"""Shared media format constants used across processing stages."""

from typing import Final

OUTPUT_WIDTH: Final = 1080
OUTPUT_HEIGHT: Final = 1920
OUTPUT_CENTER_X: Final = OUTPUT_WIDTH // 2

WAV_SAMPLE_RATE: Final = 16_000
WAV_CHANNELS: Final = 1
WAV_SAMPLE_WIDTH_BYTES: Final = 2
WAV_READ_FRAMES: Final = 4_000

OVERLAY_FONT_SIZE: Final = 24
OVERLAY_BOTTOM_MARGIN: Final = 50
PROGRESS_BUCKET_PERCENT: Final = 5
