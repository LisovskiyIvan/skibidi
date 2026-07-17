"""Tests for the dependency-free .env loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from video_processor.env_loader import _apply_env_file, load_env_file


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the keys we manipulate so tests are isolated."""
    for key in ("FOO", "BAR", "BAZ", "QUOTED", "EXPORTED"):
        monkeypatch.delenv(key, raising=False)


class TestApplyEnvFile:
    def test_plain_key_value(self, tmp_path: Path, _clean_env: None) -> None:
        env = tmp_path / ".env"
        env.write_text("FOO=bar\n", encoding="utf-8")
        _apply_env_file(env)
        assert os.environ["FOO"] == "bar"

    def test_strips_surrounding_quotes(self, tmp_path: Path, _clean_env: None) -> None:
        env = tmp_path / ".env"
        env.write_text('QUOTED="hello world"\n', encoding="utf-8")
        _apply_env_file(env)
        assert os.environ["QUOTED"] == "hello world"

    def test_handles_export_prefix(self, tmp_path: Path, _clean_env: None) -> None:
        env = tmp_path / ".env"
        env.write_text("export EXPORTED=value\n", encoding="utf-8")
        _apply_env_file(env)
        assert os.environ["EXPORTED"] == "value"

    def test_ignores_comments_and_blanks(self, tmp_path: Path, _clean_env: None) -> None:
        env = tmp_path / ".env"
        env.write_text("# a comment\n\nFOO=1\n\n# another\n", encoding="utf-8")
        _apply_env_file(env)
        assert os.environ["FOO"] == "1"
        assert "BAR" not in os.environ

    def test_does_not_override_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FOO", "from-shell")
        env = tmp_path / ".env"
        env.write_text("FOO=from-file\n", encoding="utf-8")
        _apply_env_file(env)
        assert os.environ["FOO"] == "from-shell"


class TestLoadEnvFile:
    def test_returns_none_when_no_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        missing = tmp_path / "does-not-exist"
        monkeypatch.setattr(
            "video_processor.env_loader._candidate_env_paths",
            lambda: [missing],
        )
        assert load_env_file() is None

    def test_loads_from_cwd(
        self, tmp_path: Path, _clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = tmp_path / ".env"
        env.write_text("BAR=baz\n", encoding="utf-8")
        monkeypatch.setattr(
            "video_processor.env_loader._candidate_env_paths",
            lambda: [env],
        )
        loaded = load_env_file()
        assert loaded == env
        assert os.environ["BAR"] == "baz"
