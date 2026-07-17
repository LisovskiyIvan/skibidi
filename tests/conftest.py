"""Shared pytest fixtures for the video_processor test suite.

Provides a common :class:`PipelineConfig` factory so that individual test
modules no longer need to declare their own ``_cfg`` / ``_config`` helper.
The factory accepts arbitrary keyword overrides that are merged on top of a
minimal base configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from video_processor.config import PipelineConfig


@pytest.fixture
def make_config() -> Any:
    """Return a factory that builds a :class:`PipelineConfig` from overrides.

    Usage::

        def test_something(make_config):
            cfg = make_config(brightness=0.1)
            assert cfg.brightness == 0.1
    """

    def _factory(**overrides: Any) -> PipelineConfig:
        base: dict[str, Any] = {"input": Path("in.mp4")}
        base.update(overrides)
        return PipelineConfig(**base)

    return _factory
