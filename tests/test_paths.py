"""Tests for rendered clip collection and sorting."""

import json
from pathlib import Path
from typing import Any

from video_processor.paths import collect_upload_paths, sort_clip_paths


def test_clip_paths_are_sorted_by_numeric_index() -> None:
    paths = [Path("clip_10.mp4"), Path("clip_2.mp4"), Path("clip_1.mp4")]
    assert [path.name for path in sort_clip_paths(paths)] == [
        "clip_1.mp4",
        "clip_2.mp4",
        "clip_10.mp4",
    ]


def test_collect_upload_paths_uses_numeric_order(tmp_path: Path, make_config: Any) -> None:
    final = tmp_path / "final"
    final.mkdir()
    for name in ("clip_10_sub.mp4", "clip_2_sub.mp4", "clip_1_sub.mp4"):
        (final / name).write_bytes(b"video")

    paths = collect_upload_paths(make_config(output_dir=tmp_path, burn_subs=True))
    assert [path.name for path in paths] == [
        "clip_1_sub.mp4",
        "clip_2_sub.mp4",
        "clip_10_sub.mp4",
    ]


def test_collect_upload_paths_prefers_current_manifest(tmp_path: Path, make_config: Any) -> None:
    final = tmp_path / "final"
    final.mkdir()
    current = final / "clip_00_sub.mp4"
    stale = final / "clip_99_sub.mp4"
    current.write_bytes(b"current")
    stale.write_bytes(b"stale")
    (final / "resume-manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "total_segments": 1,
                "segments": {
                    "0": {
                        "name": current.name,
                        "size": current.stat().st_size,
                        "mtime_ns": current.stat().st_mtime_ns,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    paths = collect_upload_paths(make_config(output_dir=tmp_path, burn_subs=True))

    assert paths == [current]


def test_collect_upload_paths_rejects_manifest_path_traversal(
    tmp_path: Path, make_config: Any
) -> None:
    final = tmp_path / "final"
    final.mkdir()
    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"private")
    (final / "resume-manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "total_segments": 1,
                "segments": {"0": {"name": "../private.mp4"}},
            }
        ),
        encoding="utf-8",
    )

    assert collect_upload_paths(make_config(output_dir=tmp_path)) == []
