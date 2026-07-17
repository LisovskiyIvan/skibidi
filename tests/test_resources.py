"""Tests for side-effect-free resource path resolution."""

import sys
from pathlib import Path

import pytest

import video_processor.resources as resources
from video_processor.resources import (
    get_default_credentials_path,
    get_default_model_dir,
)


def test_credentials_getter_does_not_create_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    expected = tmp_path / "video_processor" / "client_secret.json"

    assert get_default_credentials_path() == expected
    assert not expected.parent.exists()


def test_model_override_is_absolute_and_cwd_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "models" / "vosk"
    monkeypatch.setenv("VIDEO_PROCESSOR_MODEL_DIR", str(model))
    monkeypatch.chdir(tmp_path)

    assert get_default_model_dir() == model.resolve()


def test_model_resolution_prefers_override_then_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    override = tmp_path / "override"
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("VIDEO_PROCESSOR_MODEL_DIR", str(override))
    assert get_default_model_dir() == override.resolve()

    monkeypatch.delenv("VIDEO_PROCESSOR_MODEL_DIR")
    assert get_default_model_dir() == bundle / "vosk-model-small-ru-0.22"


def test_source_model_path_does_not_follow_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VIDEO_PROCESSOR_MODEL_DIR", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.chdir(tmp_path)

    expected = Path(resources.__file__).resolve().parent.parent
    assert get_default_model_dir() == expected / "vosk-model-small-ru-0.22"
