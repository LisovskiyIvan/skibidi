from pathlib import Path

import tomli

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_metadata_and_typed_marker() -> None:
    project = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["readme"] == "README.md"
    assert project["license"] == "MIT"
    assert project["urls"]["Repository"].startswith("https://github.com/")
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "VOSK_MODEL_LICENSE").is_file()
    assert (ROOT / "video_processor" / "py.typed").is_file()


def test_windows_extra_covers_promised_optional_features() -> None:
    extras = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]
    windows = "\n".join(extras["windows"])

    assert "pyinstaller" in windows.lower()
    assert "faster-whisper" in windows
    assert "google-api-python-client" in windows
    assert "yt-dlp" in windows

    gui = "\n".join(extras["gui"])
    assert "faster-whisper" in gui
    assert "google-api-python-client" in gui
    assert "yt-dlp" in gui
