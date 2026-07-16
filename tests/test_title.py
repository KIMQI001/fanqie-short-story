"""Unit tests for title.py."""
from __future__ import annotations

from fanqie_short_story.body import Body
from fanqie_short_story.title import generate_titles


def test_generate_titles_returns_n_candidates() -> None:
    body = Body(text="x", char_count=1)
    def fake(prompt, **kw):
        # 5 lines, one per title
        return "重生侯府\n侯门嫡女的复仇\n我在古代开撕\n那一夜我重生了\n血洗侯门"
    titles = generate_titles(body, "hook", "chuanqi", n=5, llm=fake)
    assert titles == ["重生侯府", "侯门嫡女的复仇", "我在古代开撕",
                      "那一夜我重生了", "血洗侯门"]


def test_generate_titles_strips_empty_lines() -> None:
    body = Body(text="x", char_count=1)
    def fake(prompt, **kw):
        return "\n\ntitle1\n\n\ntitle2\n"
    titles = generate_titles(body, "h", "xianyan", n=2, llm=fake)
    assert titles == ["title1", "title2"]


def test_generate_titles_deduplicates_and_caps() -> None:
    body = Body(text="x", char_count=1)
    def fake(prompt, **kw):
        return "title1\ntitle1\ntitle2\ntitle3\ntitle4\ntitle5"
    titles = generate_titles(body, "h", "x", n=3, llm=fake)
    assert titles == ["title1", "title2", "title3"]
