"""Unit tests for synopsis.py."""
from __future__ import annotations

from fanqie_short_story.body import Body
from fanqie_short_story.synopsis import generate_synopsis


def test_generate_synopsis_strips_fences_and_returns_text() -> None:
    body = Body(text="第一章\n\n" + "林晚睁开眼，发现自己重生了。" * 50, char_count=200)
    def fake(prompt, **kw):
        return "```\n林晚重生回侯府，发现前世夫君是凶手。\n```"
    syn = generate_synopsis(body, "hook", "chuanqi", n=120, llm=fake)
    assert "林晚" in syn
    assert "```" not in syn


def test_generate_synopsis_returns_plain_text_when_no_fences() -> None:
    body = Body(text="x", char_count=1)
    def fake(prompt, **kw):
        return "  \n林晚重生归来的故事。\n  "
    syn = generate_synopsis(body, "h", "chuanqi", n=50, llm=fake)
    assert syn == "林晚重生归来的故事。"
