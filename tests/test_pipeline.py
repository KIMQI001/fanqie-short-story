"""Unit tests for pipeline.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from fanqie_short_story.body import Body
from fanqie_short_story.outline import Outline
from fanqie_short_story.pipeline import GenerationFailed, generate_story


def _outline() -> Outline:
    return Outline(
        title_seed="林晚",
        beats=["起：重生", "承：搜集", "转：反击", "合：破局", "收：归隐"],
        characters=[{"name": "林晚", "role": "主角", "arc": ""}],
        setting="侯府",
        central_conflict="林晚必须先发制人",
    )


def test_generate_story_writes_all_outputs(tmp_path: Path, fake_config) -> None:
    def fake_outline(*args, **kw):
        return _outline()
    def fake_body(*args, **kw):
        # Sized to ~1410 chars; target 1400 → window 1120-1680, passes length.
        text = ("第一章 重生\n\n刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 50
                + "真相大白，归隐山林。")
        return Body.from_text(text)
    def fake_titles(*args, **kw):
        return ["重生侯府", "侯门嫡女", "血洗侯门"]
    def fake_synopsis(*args, **kw):
        return "林晚重生回侯府，发现前世夫君是凶手。"
    def fake_cover(*args, **kw):
        # Mimic real cover_gen: write cover.jpg into <output_dir>/<slug>/.
        slug = kw.get("slug") or args[0]
        output_dir = kw.get("output_dir") or args[3]
        (Path(output_dir) / slug).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / slug / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        return "minimax"
    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.generate_titles", side_effect=fake_titles), \
         patch("fanqie_short_story.pipeline.generate_synopsis", side_effect=fake_synopsis), \
         patch("fanqie_short_story.pipeline.generate_cover", side_effect=fake_cover):
        out = generate_story(
            hook="重生侯府", genre="chuanqi", target_length=1400,
            output_dir=tmp_path, config=fake_config,
        )
    assert (out / "outline.md").exists()
    assert (out / "body.txt").exists()
    assert (out / "titles.txt").exists()
    assert (out / "synopsis.md").exists()
    assert (out / "cover.jpg").exists()
    assert (out / "manifest.json").exists()


def test_generate_story_retries_on_critique_fail(tmp_path: Path, fake_config) -> None:
    """First body is bad (weak hook, unresolved ending, off-length).
    Second body is good (passes all gates). Verify retry happens."""
    call_count = {"body": 0}
    def fake_outline(*args, **kw):
        return _outline()
    def fake_body(*args, **kw):
        call_count["body"] += 1
        if call_count["body"] == 1:
            # Weak setup, no hook signals, unresolved ending, off-length.
            text = ("在一个阳光明媚的早晨，我醒来了。"
                    + ("情节。" * 800) + "未完待续")
            return Body.from_text(text)
        # Sized to ~1629 chars; target 2000 → window 1600-2400, passes length.
        # Has 撞见 + 必须 hooks, ends with 真相大白...归隐.
        text = ("刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 70
                + "真相大白，归隐山林，从此再无风波。")
        return Body.from_text(text)
    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=2000,
            output_dir=tmp_path, config=fake_config,
        )
    assert call_count["body"] >= 2  # retried at least once
    assert (out / "body.txt").exists()


def test_generate_story_raises_after_max_retries(tmp_path: Path, fake_config) -> None:
    def fake_outline(*args, **kw):
        return _outline()
    def always_bad(*args, **kw):
        # Always fails hook (no signals), ending (未完待续), length (14 chars).
        return Body.from_text("未完待续" + ("x" * 10))
    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=always_bad), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        with pytest.raises(GenerationFailed) as exc_info:
            generate_story(
                hook="h", genre="chuanqi", target_length=1000,
                output_dir=tmp_path, config=fake_config,
            )
    assert (exc_info.value.output_dir / "_failed").exists()


def test_generate_story_continues_when_cover_fails(tmp_path: Path, fake_config) -> None:
    """Cover failure must NOT block the rest of the pipeline."""
    def fake_outline(*args, **kw):
        return _outline()
    def fake_body(*args, **kw):
        text = ("第一章 重生\n\n刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 50
                + "真相大白，归隐山林。")
        return Body.from_text(text)
    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover",
               side_effect=RuntimeError("comfyui down")):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1400,
            output_dir=tmp_path, config=fake_config,
        )
    assert (out / "body.txt").exists()
    assert (out / "manifest.json").exists()
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["cover_backend"] is None
