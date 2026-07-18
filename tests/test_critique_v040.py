"""Tests for v0.4.0 critique.py extensions — 6 写作禁区 rules.

The v0.3.4 heuristic has 4 gates (hook / ending / length / pov). v0.4.0
ADDS 6 写作禁区 (writing-forbidden) rules that the methodology treats as
AI-odor tells:
  1. weather_or_dream_opener — first 100 chars must not be 天气/梦境/身世
  2. three_paragraph_monologue — 3 consecutive internal-monologue paragraphs
  3. abstract_metaphor_cliche — 潮水/深渊/齿轮/光芒/牢笼/风暴/星辰/利刃
  4. passive_protagonist_full_chapter — protagonist makes no active choice
  5. twist_without_setup — 大反转前 2000 字内无物证/规则/言行伏笔
  6. missing_memory_object — no concrete memory object (婚书/病历/亲子鉴定/...)

Existing rules stay; new rules are additive via a separate function.
Methodology source: tianyayu6/fanqie-hit-short-story methodology.md, the
6-item 写作禁区 list.
"""
from __future__ import annotations

import re

from fanqie_short_story.body import Body
from fanqie_short_story.critique import (
    FORBIDDEN_WRITE_PATTERNS,
    writing_forbidden_critique,
    WritingForbiddenReport,
)


# ---------------------------------------------------------------------------
# 写作禁区 catalogue — sanity check the strings before they ship
# ---------------------------------------------------------------------------


def test_forbidden_write_patterns_is_six_rules_with_chinese_names() -> None:
    """6 named rules; each with a Chinese name + detector substring list."""
    assert isinstance(FORBIDDEN_WRITE_PATTERNS, list)
    assert len(FORBIDDEN_WRITE_PATTERNS) == 6
    for name, _detector in FORBIDDEN_WRITE_PATTERNS:
        assert isinstance(name, str) and name.strip()
        assert any("\u4e00" <= ch <= "\u9fff" for ch in name), \
            f"non-CJK rule name: {name!r}"


# ---------------------------------------------------------------------------
# Detector behaviour — one test per rule
# ---------------------------------------------------------------------------


def test_writing_forbidden_flags_weather_or_dream_opener() -> None:
    """前 100 字出现 weather/dream/身世/world-building → fail."""
    body = Body.from_text("阳光正好，她拉开窗帘。")  # '阳光正好' = weather opener
    rep = writing_forbidden_critique(body)
    assert any("weather_or_dream_opener" in r for r in rep.failed_rules), \
        f"expected weather_or_dream_opener in {rep.failed_rules}"
    assert any("weather_or_dream_opener" in n for n in rep.notes), \
        f"expected rule name in note; got {rep.notes}"


def test_writing_forbidden_passes_with_conflict_opener() -> None:
    """A clean 第一章 opener with conflict + protagonist goal should not
    trigger weather/dream rule."""
    body = Body.from_text(
        "弹幕警告：「林晚活不过三章。」我撕掉婚书，把行李箱推到门口。\n\n"
        "我把录像带压在病历下，带着外卖单和转账记录走了。主角签字。"
    )
    rep = writing_forbidden_critique(body)
    assert not any("weather_or_dream_opener" in r for r in rep.failed_rules)


def test_writing_forbidden_flags_three_paragraph_monologue() -> None:
    """3 consecutive '我想...' internal-monologue paragraphs → fail."""
    text = (
        "第一章 她转身离开。\n\n"
        "我想了一整天。我觉得，也许。\n\n"
        "我想，这不对。我想起那句话。我又想了想。\n\n"
        "我想，我会变强。我终于明白。\n\n"
        "外面下起了雨。"
    )
    # Use raw .text assignment so blank-line paragraph separators survive
    # (Body.from_text strips all whitespace, including paragraph breaks).
    body = Body(text=text, char_count=len(text))
    rep = writing_forbidden_critique(body)
    assert any("three_paragraph_monologue" in r for r in rep.failed_rules), \
        f"expected rule; got {rep.failed_rules}"


def test_writing_forbidden_flags_abstract_metaphor_cliche() -> None:
    """Body containing 潮水/深渊/齿轮/光芒/牢笼/风暴/星辰/利刃 as
    standalone abstract metaphors → fail."""
    for term in ("潮水", "深渊", "齿轮", "光芒", "牢笼", "风暴", "星辰", "利刃"):
        body = Body.from_text(
            f"她的心如{term}般转动，弹幕说她活不过三章。\n\n"
            f"我把录像带压在病历下，带着外卖单和转账记录签了字。"
        )
        rep = writing_forbidden_critique(body)
        assert any("abstract_metaphor_cliche" in r for r in rep.failed_rules), \
            f"term {term!r} should trigger; got failed={rep.failed_rules}"


def test_writing_forbidden_passes_with_object_substitute() -> None:
    """Body that uses a concrete object in place of abstract metaphor
    should NOT trip the 写作禁区 rules."""
    body = Body.from_text(
        "我握着那盘旧录像带，看着婚书上的签名，攥紧了外卖单。\n"
        "病历压在床头柜上。\n"
        "弹幕倒计时还剩三天。"
    )
    rep = writing_forbidden_critique(body)
    # Must pass all 6 rules.
    assert rep.passed, f"clean object-driven body should pass; got failed={rep.failed_rules}, notes={rep.notes}"


def test_writing_forbidden_flags_missing_memory_object() -> None:
    """Body with NO concrete memory object (no 录像带/婚书/病历/亲子鉴定/
    倒计时/账本/弹幕截图/外卖单/旧照片/转账记录) → fail."""
    text = "第一段：开始。\n这是故事情节，没有具体物件。\n继续发展。"
    body = Body.from_text(text)
    rep = writing_forbidden_critique(body)
    assert any("missing_memory_object" in r for r in rep.failed_rules)


def test_writing_forbidden_passed_when_everything_ok() -> None:
    """Clean body with conflict opener + memory object + no clichés → passed=True."""
    text = (
        "弹幕说：「林晚活不过三章。」\n"
        "我攥紧录像带，把外卖单压在病历下面，在转账记录页签了字。\n\n"
        "我走出去，按了门铃。\n\n"
        "真相是，我早就看过那段录像带。"
    )
    body = Body.from_text(text)
    rep = writing_forbidden_critique(body)
    assert rep.passed, f"expected passed=True; failed={rep.failed_rules}, notes={rep.notes}"


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


def test_writing_forbidden_report_shape() -> None:
    """WritingForbiddenReport must have the right fields and serialize cleanly."""
    body = Body.from_text("阳光正好。")
    rep = writing_forbidden_critique(body)
    assert isinstance(rep, WritingForbiddenReport)
    assert isinstance(rep.passed, bool)
    assert isinstance(rep.failed_rules, list)
    assert isinstance(rep.notes, list)
    assert rep.passed is False
    assert len(rep.failed_rules) > 0
    assert len(rep.notes) == len(rep.failed_rules)


# ---------------------------------------------------------------------------
# Integration with existing heuristic_critique — combined check helper
# ---------------------------------------------------------------------------


def test_combined_heuristic_and_writing_forbidden_critique() -> None:
    """A helper that BOTH the v0.3.4 4 gates AND v0.4.0 6 写作禁区 rules
    should report failures from EITHER side without losing any."""
    from fanqie_short_story.critique import combined_heuristic_critique
    # Body with weather opener AND length too short — both should fail.
    body = Body.from_text("阳光正好，她走去厨房。")
    rep = combined_heuristic_critique(
        body=body, hook="x", target_length=10000,
    )
    # Either the length gate OR the weather rule must fire.
    assert rep.passed is False
    # notes should mention at least one rule from the writing-forbidden list.
    blob = "\n".join(rep.notes)
    assert "weather" in blob or "length" in blob or "字数" in blob
