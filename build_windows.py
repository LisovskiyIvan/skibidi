# Build executable for Windows
# Run: python build_windows.py
# Or use GitHub Actions (see .github/workflows/build.yml)

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def download_file(url: str, dest: Path, desc: str):
    """Download file with progress."""
    print(f"Downloading {desc}...")
    print(f"  URL: {url}")
    print(f"  Dest: {dest}")

    def report_hook(block_num, block_size, total_size):
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

    # Download ffmpeg from gyano.dev (official builds)
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


def check_pyinstaller():
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


def install_pyinstaller():
    """Install pyinstaller."""
    print("Installing PyInstaller...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)


def create_spec_file(
    build_dir: Path,
    script_path: Path,
    ffmpeg_dir: Path,
    model_dir: Path,
    fonts_dir: Path,
) -> Path:
    """Create PyInstaller spec file."""

    # Calculate relative paths for the spec file
    script_name = script_path.stem

    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

import sys
sys.setrecursionlimit(5000)

block_cipher = None

# Data files to include
added_files = [
    # FFmpeg binaries
    ('{ffmpeg_dir.as_posix()}/ffmpeg.exe', '.'),
    ('{ffmpeg_dir.as_posix()}/ffprobe.exe', '.'),
    
    # Vosk model
    ('{model_dir.as_posix()}', 'vosk-model-small-ru-0.22'),
    
    # Fonts
    ('{fonts_dir.as_posix()}', 'assets/oswald/static'),
]

a = Analysis(
    ['{script_path.as_posix()}'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=['vosk', 'tkinter', 'wave', 'json', 'math'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='VideoProcessor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
"""

    spec_path = build_dir / "VideoProcessor.spec"
    spec_path.write_text(spec_content, encoding="utf-8")
    return spec_path


def patch_script_for_exe(script_path: Path, build_dir: Path) -> Path:
    """Create modified version of script for exe build."""

    content = script_path.read_text(encoding="utf-8")

    # Add code to detect if running from exe and set paths accordingly
    exe_patch = '''
# --- AUTO-INJECTED BY BUILD SCRIPT ---
import sys
import os

def get_resource_path(relative_path):
    """Get path to resource, works for dev and PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Set ffmpeg paths for bundled exe
if hasattr(sys, '_MEIPASS'):
    FFMPEG = get_resource_path("ffmpeg.exe")
    FFPROBE = get_resource_path("ffprobe.exe")
    MODEL_DIR = Path(get_resource_path("vosk-model-small-ru-0.22"))
    SUBTITLE_FONT = get_resource_path("assets/oswald/static/Oswald-Bold.ttf")
else:
    # Keep original values for development mode
    pass

# --- END AUTO-INJECTED ---

'''

    # Find where to insert (after imports, before CONFIG)
    lines = content.split("\n")
    import_end = 0
    for i, line in enumerate(lines):
        if line.startswith("from ") or line.startswith("import "):
            import_end = i + 1

    # Insert the patch
    lines.insert(import_end, exe_patch)

    # Modify CONFIG section to use get_resource_path for exe
    new_lines = []
    for line in lines:
        if "SUBTITLE_FONT = " in line and "get_resource_path" not in line:
            line = 'SUBTITLE_FONT = get_resource_path("assets/oswald/static/Oswald-Bold.ttf")'
        new_lines.append(line)

    modified_content = "\n".join(new_lines)

    # Write modified script
    modified_path = build_dir / "pipeline_vosk_build.py"
    modified_path.write_text(modified_content, encoding="utf-8")
    return modified_path


def build_exe(spec_path: Path, dist_dir: Path):
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


def main():
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

    script_path = script_dir / "pipeline_vosk.py"

    if not script_path.exists():
        print(f"Error: Script not found: {script_path}")
        sys.exit(1)

    # Setup dependencies
    print("\n" + "-" * 60)
    print("Step 1: Downloading dependencies...")
    print("-" * 60)

    ffmpeg_dir = setup_ffmpeg(build_dir)
    model_dir = setup_vosk_model(build_dir)
    fonts_dir = setup_fonts(build_dir)

    # Check PyInstaller
    print("\n" + "-" * 60)
    print("Step 2: Checking PyInstaller...")
    print("-" * 60)

    if not check_pyinstaller():
        install_pyinstaller()
    else:
        print("PyInstaller already installed")

    # Create modified script
    print("\n" + "-" * 60)
    print("Step 3: Preparing build script...")
    print("-" * 60)

    modified_script = patch_script_for_exe(script_path, build_dir)
    print(f"Created: {modified_script}")

    # Create spec file
    print("\n" + "-" * 60)
    print("Step 4: Creating spec file...")
    print("-" * 60)

    spec_path = create_spec_file(
        build_dir, modified_script, ffmpeg_dir, model_dir, fonts_dir
    )
    print(f"Created: {spec_path}")

    # Build
    print("\n" + "-" * 60)
    print("Step 5: Building executable...")
    print("-" * 60)

    build_exe(spec_path, dist_dir)

    print("\n" + "=" * 60)
    print("SUCCESS!")
    print("=" * 60)
    print(f"\nYour executable is ready at:")
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
