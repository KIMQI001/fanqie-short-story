"""Unit tests for manifest.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fanqie_short_story.manifest import StoryManifest, write_manifest


def test_write_manifest_creates_json(tmp_path: Path) -> None:
    m = StoryManifest(
        slug="x", hook="h", genre="chuanqi", target_length=12000,
        actual_length=11823, tone="sweet", model="MiniMax-M2.7",
        created_at=datetime(2026, 7, 16, 10, 30, tzinfo=timezone.utc),
        critique_iterations=1, critique_notes=["pass"],
        cover_backend="minimax", llm_calls=4, estimated_tokens=28500,
        output_files=["outline.md", "body.txt"],
    )
    out = write_manifest(tmp_path, m)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["slug"] == "x"
    assert data["target_length"] == 12000
    assert data["created_at"] == "2026-07-16T10:30:00+00:00"


def test_write_manifest_preserves_unicode(tmp_path: Path) -> None:
    m = StoryManifest(
        slug="chongsheng", hook="重生侯府", genre="chuanqi",
        target_length=12000, actual_length=11823, tone=None,
        model="MiniMax-M2.7",
        created_at=datetime(2026, 7, 16, 10, 30, tzinfo=timezone.utc),
        critique_iterations=0, critique_notes=[],
        cover_backend=None, llm_calls=0, estimated_tokens=0,
        output_files=[],
    )
    out = write_manifest(tmp_path, m)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["hook"] == "重生侯府"
