"""Unit tests for outline.py."""
from __future__ import annotations

import pytest

from fanqie_short_story.outline import Outline, generate_outline


def _fake_llm_outline(prompt: str, **kw) -> str:
    return (
        "# 大纲\n\n"
        "## 幕\n"
        "1. 起：主角重生，撞见凶手\n"
        "2. 承：搜集证据，发现线索\n"
        "3. 转：凶手反击，设下陷阱\n"
        "4. 合：主角破局，凶手伏法\n"
        "5. 收：主角和盟友重归平静\n\n"
        "## 人物\n"
        "- 林晚：主角，从被动到主动\n"
        "- 沈墨：反派，前世夫君\n\n"
        "## 设定\n"
        "架空王朝，侯府后宅。\n\n"
        "## 核心冲突\n"
        "林晚重生后必须在沈墨加害前先发制人。"
    )


def test_generate_outline_returns_structured_outline() -> None:
    o = generate_outline(
        hook="重生后我成了侯府嫡女，发现前世夫君是害我的凶手",
        genre="chuanqi",
        target_length=12000,
        tone="sweet_with_suspense",
        llm=_fake_llm_outline,
    )
    assert isinstance(o, Outline)
    assert len(o.beats) == 5
    assert o.beats[0].startswith("起")
    assert any("林晚" in c["name"] for c in o.characters)
    assert "侯府" in o.setting
    assert "沈墨" in o.central_conflict or "凶手" in o.central_conflict


def test_generate_outline_uses_target_length_and_genre_in_prompt() -> None:
    seen: dict = {}

    def spy(prompt: str, **kw):
        seen["prompt"] = prompt
        return (
            "## 幕\n1. x\n2. y\n3. z\n4. w\n5. v\n\n"
            "## 人物\n- 主角\n\n## 设定\ns\n\n## 核心冲突\nc"
        )

    generate_outline("hook", "chuanqi", 12000, "sweet_with_suspense", llm=spy)
    assert "12000" in seen["prompt"]
    assert "chuanqi" in seen["prompt"]


def test_generate_outline_rejects_unknown_genre() -> None:
    with pytest.raises(ValueError, match="genre"):
        generate_outline("h", "bogus", 1000, "sweet", llm=_fake_llm_outline)


def test_outline_to_prompt_string_roundtrip() -> None:
    """Outline.to_prompt_string should produce parseable markdown that
    contains the same beats/characters/setting/conflict."""
    o = Outline(
        title_seed="x",
        beats=["起：A", "承：B", "转：C", "合：D", "收：E"],
        characters=[{"name": "甲", "role": "主角", "arc": "成长"}],
        setting="古代",
        central_conflict="AB 冲突",
    )
    s = o.to_prompt_string()
    assert "## 幕" in s
    assert "起：A" in s
    assert "甲" in s
    assert "古代" in s
    assert "AB 冲突" in s


def test_outline_parses_minimalist_input() -> None:
    """If the LLM produces a near-empty body, parser should not crash."""
    from fanqie_short_story.outline import _parse_outline_md
    o = _parse_outline_md("## 幕\n1. 起\n2. 承\n3. 转\n4. 合\n5. 收\n")
    assert len(o.beats) == 5
    assert o.characters == []
    assert o.setting == ""
