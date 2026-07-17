# Current Project Plan

Status updated: 2026-07-17.

## Completed release engineering

- `pyproject.toml` is the package metadata source, with MIT metadata, project
  URLs, supported Python classifiers, optional feature extras, a PyInstaller 6
  build extra, and PEP 561 package data.
- `uv.lock` is the deterministic dependency source for local setup and CI.
- CI runs format, lint, strict mypy, a Python 3.9-3.14 pytest matrix, package
  build, clean wheel install, and import/version smoke checks.
- `VideoProcessor.spec` is source-controlled and defines a real onedir build
  with `EXE(exclude_binaries=True)` followed by `COLLECT`.
- `build_windows.py` owns all Windows asset preparation. Downloaded archives
  require SHA-256, the actual font is mandatory, and the tracked Vosk model is
  reused without deleting repository data.
- Windows CI calls the shared build script, uploads the onedir tree plus ZIP and
  checksum, and grants release write permission only to the tag release job.
- MIT `LICENSE`, conservative `THIRD_PARTY_NOTICES`, and Windows build/licensing
  documentation are present.

## Current behavior

- Resume is manifest- and fingerprint-based and validates outputs with ffprobe.
- Rendered output is published atomically; failed `.part` output is removed.
- GUI cancellation is cooperative, and queued segment work is cancelled after a
  failure or cancellation reaches the pipeline.
- Successful runs clean WAV/segment intermediates unless configured to keep
  them; ASS and final outputs remain available.
- Upload, download, and faster-whisper remain explicit optional features.

## Release blockers

1. Select immutable/versioned FFmpeg and Oswald archives for Windows releases,
   independently establish their SHA-256 values, and configure the documented
   GitHub repository variables. The build intentionally fails without them.
2. Run the Windows workflow and smoke-test the complete onedir folder on a clean
   Windows host, including Vosk, Whisper, YouTube upload, and yt-dlp paths.

## Next priorities

1. Resolve the external FFmpeg and Oswald asset manifest blocker above.
2. Create a signed `v0.1.0` release only after the Windows checksum and clean-host
   smoke test have been reviewed.
3. Keep Python compatibility aligned with the CI matrix and remove a Python
   version only through an explicit metadata and lockfile change.
4. Treat runtime architecture changes as a separate effort from packaging so a
   release-engineering change does not silently alter pipeline behavior.

## Git history policy

The existing tracked Vosk model files remain untouched. Removing their blobs
from old commits would require a separate, explicitly approved history rewrite
(for example with `git filter-repo`), coordinated clone migration, and a
force-push. It is not part of normal cleanup, packaging, or release automation.

## Verification commands

```bash
uv lock
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

Windows verification is performed by `.github/workflows/build-windows.yml`
after the required URL/hash manifest inputs are configured.
