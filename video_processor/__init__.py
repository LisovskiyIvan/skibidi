"""Video transcription pipeline package.

Split into logical layers:
- core: business logic (ffmpeg, transcription, subtitles, pipeline orchestration,
  YouTube upload, resources, progress, errors)
- cli: command-line interface
- ui: optional Tkinter GUI
"""

__version__ = "0.1.0"
