# Build executable for Windows
# Run: python build_windows.py
# Or use GitHub Actions (see .github/workflows/build.yml)

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


def download_file(url: str, dest: Path, desc: str) -> None:
    """Download file with progress."""
    print(f"Downloading {desc}...")
    print(f"  URL: {url}")
    print(f"  Dest: {dest}")

    def report_hook(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        percent = min(downloaded * 100 / total_size, 100) if total_size > 0 else 0
        sys.stdout.write(f"\r  Progress: {percent:.1f}%")
        sys.stdout.flush()

    urllib.request.urlretrieve(url, dest, reporthook=report_hook)
    print()  # New line after progress


def setup_ffmpeg(build_dir: Path) -> Path:
    """Download and extract ffmpeg for Windows."""
    ffmpeg_dir = build_dir / "ffmpeg"
    ffmpeg_exe = ffmpeg_dir / "ffmpeg.exe"

    if ffmpeg_exe.exists():
        print("FFmpeg already exists, skipping download")
        return ffmpeg_dir

    # Download ffmpeg from gyan.dev (official builds)
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    zip_path = build_dir / "ffmpeg.zip"

    download_file(url, zip_path, "FFmpeg")

    print("Extracting FFmpeg...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(build_dir)

    # Find extracted folder (name varies by version)
    extracted_dirs = [
        d for d in build_dir.iterdir() if d.is_dir() and "ffmpeg" in d.name.lower()
    ]
    if not extracted_dirs:
        raise RuntimeError("Could not find extracted ffmpeg directory")

    # Move bin contents to ffmpeg_dir
    extracted_dir = extracted_dirs[0]
    bin_dir = extracted_dir / "bin"

    ffmpeg_dir.mkdir(exist_ok=True)
    for exe in ["ffmpeg.exe", "ffprobe.exe"]:
        src = bin_dir / exe
        if src.exists():
            shutil.copy2(src, ffmpeg_dir / exe)
            print(f"  Copied: {exe}")

    # Cleanup
    zip_path.unlink()
    shutil.rmtree(extracted_dir)

    return ffmpeg_dir


def setup_vosk_model(build_dir: Path) -> Path:
    """Download Vosk Russian model."""
    model_dir = build_dir / "vosk-model-small-ru-0.22"

    if model_dir.exists():
        print("Vosk model already exists, skipping download")
        return model_dir

    url = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
    zip_path = build_dir / "vosk-model.zip"

    download_file(url, zip_path, "Vosk model")

    print("Extracting Vosk model...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(build_dir)

    zip_path.unlink()
    print(f"  Model extracted to: {model_dir}")

    return model_dir


def setup_fonts(build_dir: Path) -> Path:
    """Setup Oswald font."""
    fonts_dir = build_dir / "assets" / "oswald" / "static"

    if fonts_dir.exists():
        print("Fonts already exist, skipping setup")
        return fonts_dir

    fonts_dir.mkdir(parents=True, exist_ok=True)

    # Download Oswald font from Google Fonts GitHub
    url = "https://github.com/googlefonts/OswaldFont/archive/refs/heads/main.zip"
    zip_path = build_dir / "oswald.zip"

    download_file(url, zip_path, "Oswald font")

    print("Extracting fonts...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(build_dir / "oswald_temp")

    # Find and copy font files
    temp_dir = build_dir / "oswald_temp"
    font_files = list(temp_dir.rglob("Oswald-Bold.ttf"))

    if font_files:
        for font_file in font_files:
            if "static" in str(font_file):
                shutil.copy2(font_file, fonts_dir / font_file.name)
                print(f"  Copied: {font_file.name}")
    else:
        print("  Warning: Could not find Oswald-Bold.ttf, using fallback")
        # Create empty file as placeholder
        (fonts_dir / "Oswald-Bold.ttf").touch()

    # Cleanup
    zip_path.unlink()
    shutil.rmtree(temp_dir)

    return fonts_dir


def check_pyinstaller() -> bool:
    """Check if pyinstaller is installed."""
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_pyinstaller() -> None:
    """Install pyinstaller."""
    print("Installing PyInstaller...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)


def build_exe(spec_path: Path, dist_dir: Path) -> None:
    """Run PyInstaller build."""
    print("\n" + "=" * 60)
    print("Building executable...")
    print("=" * 60)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(dist_dir / "build"),
        str(spec_path),
    ]

    print(f"Command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    print("\n" + "=" * 60)
    print("Build complete!")
    print(f"Executable: {dist_dir / 'VideoProcessor' / 'VideoProcessor.exe'}")
    print("=" * 60)


def main() -> None:
    """Main build process."""
    print("=" * 60)
    print("Video Processor - Windows Executable Builder")
    print("=" * 60)

    # Detect platform
    if sys.platform == "win32":
        print("Platform: Windows")
    else:
        print(f"Platform: {sys.platform}")
        print("WARNING: Building Windows exe on non-Windows platform may not work!")
        print("Consider using GitHub Actions for cross-platform builds.")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != "y":
            print("Aborted.")
            return

    # Setup directories
    script_dir = Path(__file__).parent
    build_dir = script_dir / "build_windows"
    dist_dir = script_dir / "dist_windows"

    build_dir.mkdir(exist_ok=True)
    dist_dir.mkdir(exist_ok=True)

    script_path = script_dir / "video_processor" / "__main__.py"
    if not script_path.exists():
        print(f"Error: Entry script not found: {script_path}")
        sys.exit(1)

    # Setup dependencies
    print("\n" + "-" * 60)
    print("Step 1: Downloading dependencies...")
    print("-" * 60)

    setup_ffmpeg(build_dir)
    setup_vosk_model(build_dir)
    setup_fonts(build_dir)

    # Check PyInstaller
    print("\n" + "-" * 60)
    print("Step 2: Checking PyInstaller...")
    print("-" * 60)

    if not check_pyinstaller():
        install_pyinstaller()
    else:
        print("PyInstaller already installed")

    # Use the single shared spec file from the repo root.
    print("\n" + "-" * 60)
    print("Step 3: Locating PyInstaller spec file...")
    print("-" * 60)

    spec_path = script_dir / "VideoProcessor.spec"
    if not spec_path.exists():
        print(f"Error: spec file not found: {spec_path}")
        sys.exit(1)
    print(f"Using: {spec_path}")

    # Build
    print("\n" + "-" * 60)
    print("Step 4: Building executable...")
    print("-" * 60)

    build_exe(spec_path, dist_dir)

    print("\n" + "=" * 60)
    print("SUCCESS!")
    print("=" * 60)
    print("\nYour executable is ready at:")
    print(f"  {dist_dir / 'VideoProcessor' / 'VideoProcessor.exe'}")
    print(
        f"\nYou can zip the folder '{dist_dir / 'VideoProcessor'}' and distribute it."
    )
    print("\nThe executable includes:")
    print("  - FFmpeg (ffmpeg.exe, ffprobe.exe)")
    print("  - Vosk Russian model")
    print("  - Oswald font")
    print("=" * 60)


if __name__ == "__main__":
    main()
