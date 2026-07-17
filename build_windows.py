"""Prepare verified assets and build the Windows PyInstaller onedir bundle."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

VOSK_MODEL_NAME = "vosk-model-small-ru-0.22"
VOSK_MODEL_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    sha256: str
    archive_name: str


def _asset(name: str, url: str | None, sha256: str | None, archive_name: str) -> Asset:
    if not url or not sha256:
        env_name = name.upper().replace(" ", "_")
        raise SystemExit(
            f"{name} requires a versioned URL and SHA-256. Set "
            f"VIDEO_PROCESSOR_{env_name}_URL and VIDEO_PROCESSOR_{env_name}_SHA256 "
            "or pass the corresponding command-line options."
        )
    digest = sha256.lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SystemExit(f"Invalid SHA-256 for {name}: {sha256!r}")
    return Asset(name, url, digest, archive_name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_verified(asset: Asset, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / asset.archive_name
    if destination.is_file() and _sha256(destination) == asset.sha256:
        print(f"Using verified cached {asset.name}: {destination}")
        return destination
    destination.unlink(missing_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    print(f"Downloading {asset.name}: {asset.url}")
    try:
        with (
            urllib.request.urlopen(asset.url, timeout=120) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        actual = _sha256(temporary)
        if actual != asset.sha256:
            raise RuntimeError(
                f"SHA-256 mismatch for {asset.name}: expected {asset.sha256}, got {actual}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if os.path.commonpath((root, target)) != str(root):
                raise RuntimeError(f"Unsafe path in {archive}: {member.filename}")
        bundle.extractall(destination)


def _single_file(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if not matches:
        raise RuntimeError(f"{name} was not found in the verified archive")
    return matches[0]


def setup_ffmpeg(build_dir: Path, asset: Asset) -> None:
    archive = _download_verified(asset, build_dir / "downloads")
    extraction = build_dir / "extract-ffmpeg"
    shutil.rmtree(extraction, ignore_errors=True)
    _extract_zip(archive, extraction)
    destination = build_dir / "ffmpeg"
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        shutil.copy2(_single_file(extraction, name), destination / name)
    shutil.rmtree(extraction)


def setup_oswald(build_dir: Path, asset: Asset) -> None:
    archive = _download_verified(asset, build_dir / "downloads")
    extraction = build_dir / "extract-oswald"
    shutil.rmtree(extraction, ignore_errors=True)
    _extract_zip(archive, extraction)
    destination = build_dir / "assets" / "oswald"
    shutil.rmtree(destination, ignore_errors=True)
    (destination / "static").mkdir(parents=True)
    shutil.copy2(_single_file(extraction, "Oswald-Bold.ttf"), destination / "static")
    shutil.copy2(_single_file(extraction, "OFL.txt"), destination / "OFL.txt")
    shutil.rmtree(extraction)


def setup_model(root: Path, build_dir: Path, url: str | None, sha256: str | None) -> None:
    if (root / VOSK_MODEL_NAME).is_dir():
        print(f"Using tracked Vosk model: {root / VOSK_MODEL_NAME}")
        return
    asset = _asset("Vosk model", url or VOSK_MODEL_URL, sha256, "vosk-model.zip")
    archive = _download_verified(asset, build_dir / "downloads")
    destination = build_dir / VOSK_MODEL_NAME
    shutil.rmtree(destination, ignore_errors=True)
    _extract_zip(archive, build_dir)
    if not destination.is_dir():
        raise RuntimeError(f"Verified Vosk archive did not contain {VOSK_MODEL_NAME}")


def _check_pyinstaller() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("PyInstaller is missing. Run: uv sync --locked --extra windows")
    major = int(result.stdout.strip().split(".", 1)[0])
    if major != 6:
        raise SystemExit(f"PyInstaller 6 is required, found {result.stdout.strip()}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg-url", default=os.environ.get("VIDEO_PROCESSOR_FFMPEG_URL"))
    parser.add_argument("--ffmpeg-sha256", default=os.environ.get("VIDEO_PROCESSOR_FFMPEG_SHA256"))
    parser.add_argument("--oswald-url", default=os.environ.get("VIDEO_PROCESSOR_OSWALD_URL"))
    parser.add_argument("--oswald-sha256", default=os.environ.get("VIDEO_PROCESSOR_OSWALD_SHA256"))
    parser.add_argument("--model-url", default=os.environ.get("VIDEO_PROCESSOR_VOSK_MODEL_URL"))
    parser.add_argument(
        "--model-sha256", default=os.environ.get("VIDEO_PROCESSOR_VOSK_MODEL_SHA256")
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    if sys.platform != "win32":
        raise SystemExit("Windows bundles must be built on Windows; use the GitHub workflow.")

    root = Path(__file__).resolve().parent
    build_dir = root / "build_windows"
    dist_dir = root / "dist_windows"
    ffmpeg = _asset("FFmpeg", args.ffmpeg_url, args.ffmpeg_sha256, "ffmpeg.zip")
    oswald = _asset("Oswald", args.oswald_url, args.oswald_sha256, "oswald.zip")

    setup_ffmpeg(build_dir, ffmpeg)
    setup_oswald(build_dir, oswald)
    setup_model(root, build_dir, args.model_url, args.model_sha256)
    _check_pyinstaller()

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir / "pyinstaller"),
        str(root / "VideoProcessor.spec"),
    ]
    subprocess.run(command, cwd=root, check=True)
    output = dist_dir / "VideoProcessor"
    if not (output / "VideoProcessor.exe").is_file():
        raise RuntimeError(f"PyInstaller did not create the expected onedir output: {output}")
    print(f"Windows onedir bundle: {output}")


if __name__ == "__main__":
    main()
