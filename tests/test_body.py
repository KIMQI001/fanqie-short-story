"""Unit tests for body.py."""
from __future__ import annotations

import pytest

from fanqie_short_story.body import Body, generate_body
from fanqie_short_story.outline import Outline


def _outline() -> Outline:
    return Outline(
        title_seed="重生侯府",
        beats=["起：重生撞见凶手", "承：搜集证据", "转：反派反击",
               "合：主角破局", "收：归于平静"],
        characters=[{"name": "林晚", "role": "主角", "arc": "从被动到主动"}],
        setting="架空王朝侯府",
        central_conflict="林晚必须先发制人。",
    )


def test_generate_body_returns_text_and_count() -> None:
    body_text = "第一章 重生\n\n" + ("刀光剑影之间，林晚撞见了那个身影。" * 600) + "\n\n结尾：归于平静。"
    def fake_llm(prompt, **kw):
        return body_text
    b = generate_body(_outline(), "hook", "chuanqi", 12000,
                      "sweet_with_suspense", llm=fake_llm)
    assert isinstance(b, Body)
    assert b.char_count == len(body_text.replace(" ", "").replace("\n", ""))
    assert "林晚" in b.text


def test_generate_body_includes_critique_feedback() -> None:
    seen = {}
    def spy(prompt, **kw):
        seen["prompt"] = prompt
        return "x"
    generate_body(_outline(), "h", "chuanqi", 12000, "sweet",
                  critique_feedback=["开头钩子太弱", "结尾没收束"],
                  llm=spy)
    assert "开头钩子太弱" in seen["prompt"]
    assert "结尾没收束" in seen["prompt"]


def test_generate_body_omits_critique_block_when_no_feedback() -> None:
    seen = {}
    def spy(prompt, **kw):
        seen["prompt"] = prompt
        return "x"
    generate_body(_outline(), "h", "chuanqi", 12000, "sweet", llm=spy)
    assert "上一版问题" not in seen["prompt"]


def test_body_from_text_strips_whitespace() -> None:
    b = Body.from_text("林晚 重生\n\n在 侯府。\n")
    assert b.text == "林晚 重生\n\n在 侯府。\n"
    assert b.char_count == len("林晚重生在侯府。")


def test_generate_body_strips_json_fences() -> None:
    """LLM sometimes wraps output in ```...``` even for plain text. Strip them."""
    fenced = "```\n林晚重生归来。\n刀光剑影。\n```"
    def fake(prompt, **kw):
        return fenced
    b = generate_body(_outline(), "h", "chuanqi", 100, "sweet", llm=fake)
    assert "```" not in b.text
    assert "林晚" in b.text
