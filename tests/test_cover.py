"""Unit tests for cover.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fanqie_short_story.cover import CoverError, generate_cover


def test_generate_cover_calls_cover_gen_cli(tmp_path: Path) -> None:
    seen = {}
    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        # cover_gen writes to <output>/<slug>/cover.jpg
        (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        return MagicMock(returncode=0, stdout="", stderr="")
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        backend = generate_cover(
            slug="chongsheng-houfu",
            hook="重生侯府",
            genre="chuanqi",
            output_dir=tmp_path,
        )
    assert backend in ("minimax", "comfyui", "auto")
    assert "cover_gen" in seen["cmd"][0] or "cover-gen" in seen["cmd"][0]
    assert "generate" in seen["cmd"]
    assert "--book-id" in seen["cmd"]


def test_generate_cover_raises_on_failure(tmp_path: Path) -> None:
    with patch("fanqie_short_story.cover.subprocess.run",
               return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        with pytest.raises(CoverError, match="boom"):
            generate_cover("slug", "h", "chuanqi", tmp_path)


def test_generate_cover_raises_when_no_cover_file(tmp_path: Path) -> None:
    with patch("fanqie_short_story.cover.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="", stderr="")):
        with pytest.raises(CoverError, match="cover"):
            generate_cover("slug", "h", "chuanqi", tmp_path)


def test_generate_cover_reads_backend_from_manifest(tmp_path: Path) -> None:
    """If cover_gen writes a manifest.json with a backend field, we honor it."""
    def fake_run(cmd, **kw):
        (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        manifest = tmp_path / "manifest.json"
        manifest.write_text('{"backend": "comfyui"}', encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        backend = generate_cover(
            slug="s", hook="h", genre="chuanqi", output_dir=tmp_path,
        )
    assert backend == "comfyui"
