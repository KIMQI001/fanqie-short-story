"""Unit tests for cover.py.

The wrapper drives `cover_gen` (a batch tool reading books.yaml) by
generating a single-entry yaml on the fly. cover_gen v0.1.0 does NOT accept
--book-id / --genre / --title (it has --config only) — the v0.3.3 wrapper
passed those flags and silently failed (rc=2), which is why no cover.jpg
was ever produced despite cover_gen being on PATH.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from fanqie_short_story import cover as cover_mod
from fanqie_short_story.cover import CoverError, generate_cover


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _book_id_from_config(config_path: Path) -> str:
    """Read the single-entry books.yaml the wrapper wrote and return its
    output_name (== slug). Used by fake subprocess.run to know where to put
    the cover image so the wrapper's lookup matches.
    """
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return data["books"][0]["output_name"]


def _fake_cover_gen(manifest_backend: str | None = None, produce_cover: bool = True):
    """Return a fake subprocess.run that mimics cover_gen for one book.

    Reads --output-root and --config from cmd, then writes:
      - <output_root>/<slug>/draft/cover.png   (if produce_cover)
      - <output_root>/<slug>/manifest.json    (if manifest_backend given)
    """
    def fake_run(cmd, **kw):
        out_root = Path(cmd[cmd.index("--output-root") + 1])
        config_path = Path(cmd[cmd.index("--config") + 1])
        book_id = _book_id_from_config(config_path)
        if produce_cover:
            draft = out_root / book_id / "draft"
            draft.mkdir(parents=True, exist_ok=True)
            (draft / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        if manifest_backend is not None:
            book_dir = out_root / book_id
            book_dir.mkdir(parents=True, exist_ok=True)
            (book_dir / "manifest.json").write_text(
                json.dumps({"backend": manifest_backend}), encoding="utf-8",
            )
        return MagicMock(returncode=0, stdout="ok", stderr="")
    return fake_run


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_generate_cover_invokes_cover_gen_with_config(tmp_path: Path) -> None:
    """cover_gen v0.1.0 takes --config (books.yaml), not --book-id/--genre/--title."""
    seen: dict = {}
    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _fake_cover_gen()(cmd, **kw)
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        backend = generate_cover(
            slug="chongsheng-houfu",
            hook="重生后我成了侯府嫡女",
            genre="chuanqi",
            output_dir=tmp_path,
        )
    cmd = seen["cmd"]
    assert cmd[0] == "cover_gen"
    assert cmd[1] == "generate"
    # NEW contract: --config (with a real books.yaml), --project-root, --output-root, --backend
    assert "--config" in cmd
    assert "--project-root" in cmd
    assert "--output-root" in cmd
    assert "--backend" in cmd
    # OLD contract: --book-id / --genre / --title are gone (rc=2 otherwise).
    for bad in ("--book-id", "--genre", "--title"):
        assert bad not in cmd, f"{bad} should not be passed to cover_gen v0.1.0"
    # Result: cover.png is copied into <output_dir>/<slug>/cover.jpg
    assert (tmp_path / "chongsheng-houfu" / "cover.jpg").exists()
    # No backend in manifest → wrapper returns the default (whatever was passed)
    assert backend == "auto"


def test_generate_cover_config_yaml_uses_mapped_genre(tmp_path: Path) -> None:
    """The books.yaml we generate must use the cover_gen-mapped genre
    (chuanqi → xuanhuan) so cover_gen can route to the right template."""
    captured: dict = {}
    def fake_run(cmd, **kw):
        config_path = Path(cmd[cmd.index("--config") + 1])
        captured["yaml"] = config_path.read_text(encoding="utf-8")
        return _fake_cover_gen()(cmd, **kw)
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        generate_cover(
            slug="linggu",
            hook="灵骨试炼",
            genre="chuanqi",
            output_dir=tmp_path,
        )
    yml = captured["yaml"]
    assert "books:" in yml
    assert "xuanhuan" in yml, f"chuanqi must map to xuanhuan in yaml; got: {yml}"
    # Original umbrella genre must NOT leak through (cover_gen would not know it).
    assert "genre: chuanqi" not in yml
    assert "chuanqi" not in yml
    # Required cover_gen fields are present.
    for required in ("title:", "author:", "genre:", "synopsis:", "output_name:"):
        assert required in yml
    assert "output_name: linggu" in yml


def test_generate_cover_uses_default_author(tmp_path: Path) -> None:
    """Every cover should carry the same byline ("我是btc大户") by default —
    no more "fanqie-story" leaking through to readers."""
    captured: dict = {}
    def fake_run(cmd, **kw):
        config_path = Path(cmd[cmd.index("--config") + 1])
        captured["yaml"] = config_path.read_text(encoding="utf-8")
        return _fake_cover_gen()(cmd, **kw)
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        generate_cover(
            slug="any-slug", hook="any hook", genre="chuanqi",
            output_dir=tmp_path,
        )
    yml = captured["yaml"]
    assert "author: 我是btc大户" in yml, f"default author not set; got: {yml}"
    assert "fanqie-story" not in yml, "stale fanqie-story author leaked"


def test_generate_cover_honors_explicit_title_kwarg(tmp_path: Path) -> None:
    """If a caller passes a real book title (not a synopsis), the cover gets
    the proper title — not the first 60 chars of the synopsis."""
    captured: dict = {}
    def fake_run(cmd, **kw):
        config_path = Path(cmd[cmd.index("--config") + 1])
        captured["yaml"] = config_path.read_text(encoding="utf-8")
        return _fake_cover_gen()(cmd, **kw)
    long_synopsis = "这是一段非常非常长的简介，远远超过 60 个字符，应该被截断成前 60 个字符传给 cover_gen 当标题，但现在我们显式传了 title 参数，所以应该用显式的。"
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        generate_cover(
            slug="s", hook=long_synopsis, genre="chuanqi",
            output_dir=tmp_path, title="化六亿，叶虫始祖",
        )
    yml = captured["yaml"]
    assert "title: 化六亿，叶虫始祖" in yml, f"explicit title not honored; got: {yml}"
    # And the hook-derived title (first 60 chars of synopsis) must NOT appear.
    assert long_synopsis[:60] not in yml


def test_generate_cover_falls_back_to_hook_truncation_when_no_title(
    tmp_path: Path,
) -> None:
    """When no title is passed, the legacy behavior (first 60 chars of hook)
    is preserved — keeps backwards compat for callers that only have a hook."""
    captured: dict = {}
    def fake_run(cmd, **kw):
        config_path = Path(cmd[cmd.index("--config") + 1])
        captured["yaml"] = config_path.read_text(encoding="utf-8")
        return _fake_cover_gen()(cmd, **kw)
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        generate_cover(
            slug="s", hook="灵骨试炼", genre="chuanqi", output_dir=tmp_path,
        )
    yml = captured["yaml"]
    assert "title: 灵骨试炼" in yml, f"hook-fallback title missing; got: {yml}"


# ---------------------------------------------------------------------------
# Genre mapping
# ---------------------------------------------------------------------------


def test_genre_mapping_covers_all_umbrella_genres() -> None:
    """All 5 fanqie-short-story umbrella genres must have a cover_gen mapping."""
    from fanqie_short_story.cover import _map_genre
    assert _map_genre("chuanqi") == "xuanhuan"
    assert _map_genre("xianyan") == "yanqing"
    assert _map_genre("xuanyi") == "mystery"
    assert _map_genre("tianchong") == "yanqing"
    assert _map_genre("naodong") == "other"
    # Unknown genre falls back to "other".
    assert _map_genre("future_unknown_genre") == "other"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_generate_cover_raises_on_subprocess_failure(tmp_path: Path) -> None:
    with patch(
        "fanqie_short_story.cover.subprocess.run",
        return_value=MagicMock(returncode=1, stdout="", stderr="boom"),
    ):
        with pytest.raises(CoverError, match="boom"):
            generate_cover("slug", "h", "chuanqi", tmp_path)


def test_generate_cover_raises_when_no_cover_file(tmp_path: Path) -> None:
    """Even on rc=0, if cover_gen produced no cover image, raise."""
    def fake_run(cmd, **kw):
        return MagicMock(returncode=0, stdout="", stderr="")
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        with pytest.raises(CoverError, match="cover"):
            generate_cover("slug", "h", "chuanqi", tmp_path)


def test_generate_cover_reads_backend_from_manifest(tmp_path: Path) -> None:
    """If cover_gen writes a manifest.json with backend, we honor it."""
    with patch(
        "fanqie_short_story.cover.subprocess.run",
        side_effect=_fake_cover_gen(manifest_backend="comfyui"),
    ):
        backend = generate_cover(
            slug="slug-x", hook="h", genre="chuanqi", output_dir=tmp_path,
        )
    assert backend == "comfyui"


def test_generate_cover_raises_when_cover_gen_not_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cover_mod.shutil, "which", lambda _: None)
    with pytest.raises(CoverError, match="not on PATH"):
        generate_cover("slug", "h", "chuanqi", tmp_path)


# ---------------------------------------------------------------------------
# Tempdir cleanup
# ---------------------------------------------------------------------------


def test_generate_cover_cleans_up_tempdir_on_success(tmp_path: Path) -> None:
    """After invocation, the temp config file passed via --config must be
    gone — the wrapper removed its workdir in a finally block."""
    seen_configs: list[Path] = []
    def fake_run(cmd, **kw):
        if "--config" in cmd:
            seen_configs.append(Path(cmd[cmd.index("--config") + 1]))
        return _fake_cover_gen()(cmd, **kw)
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        generate_cover(slug="s", hook="h", genre="chuanqi", output_dir=tmp_path)
    assert len(seen_configs) == 1, "wrapper did not pass --config to cover_gen"
    assert not seen_configs[0].exists(), (
        f"temp config leaked after success: {seen_configs[0]}"
    )


def test_generate_cover_cleans_up_tempdir_on_failure(tmp_path: Path) -> None:
    """Even if subprocess fails, the temp config must be cleaned up."""
    seen_configs: list[Path] = []
    def fake_run(cmd, **kw):
        if "--config" in cmd:
            seen_configs.append(Path(cmd[cmd.index("--config") + 1]))
        return MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("fanqie_short_story.cover.subprocess.run", side_effect=fake_run):
        with pytest.raises(CoverError):
            generate_cover("slug", "h", "chuanqi", tmp_path)
    assert len(seen_configs) == 1, "wrapper did not pass --config to cover_gen"
    assert not seen_configs[0].exists(), (
        f"temp config leaked after failure: {seen_configs[0]}"
    )
