# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 6 onedir build shared by local builds and GitHub Actions."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
build_assets = root / "build_windows"
model_source = root / "vosk-model-small-ru-0.22"
if not model_source.is_dir():
    model_source = build_assets / "vosk-model-small-ru-0.22"

required_paths = [
    build_assets / "ffmpeg" / "ffmpeg.exe",
    build_assets / "ffmpeg" / "ffprobe.exe",
    build_assets / "assets" / "oswald" / "static" / "Oswald-Bold.ttf",
    build_assets / "assets" / "oswald" / "OFL.txt",
    model_source,
]
missing = [str(path) for path in required_paths if not path.exists()]
if missing:
    raise SystemExit("Missing Windows build assets:\n  " + "\n  ".join(missing))

hiddenimports = ["vosk"]
collected_datas = []
collected_binaries = []
for package in ("av", "ctranslate2", "faster_whisper", "yt_dlp"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    collected_datas.extend(package_datas)
    collected_binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)
for package in ("google_auth_oauthlib", "googleapiclient"):
    hiddenimports.extend(collect_submodules(package))

a = Analysis(
    [str(root / "video_processor" / "__main__.py")],
    pathex=[str(root)],
    binaries=[
        (str(build_assets / "ffmpeg" / "ffmpeg.exe"), "."),
        (str(build_assets / "ffmpeg" / "ffprobe.exe"), "."),
        *collected_binaries,
    ],
    datas=[
        (str(model_source), "vosk-model-small-ru-0.22"),
        (str(build_assets / "assets" / "oswald"), "assets/oswald"),
        (str(root / "LICENSE"), "."),
        (str(root / "THIRD_PARTY_NOTICES"), "."),
        (str(root / "VOSK_MODEL_LICENSE"), "."),
        *collected_datas,
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoProcessor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="VideoProcessor",
)
