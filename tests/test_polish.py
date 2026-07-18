"""Unit tests for the v0.4.0 de-AI-flavor polish post-processor.

Polish runs AFTER the editor critic accepts the body and BEFORE the manifest
is finalized. intensity=0 is the explicit no-op (used for tests + A-B
comparisons); intensity≥1 applies rule-based filtering. Polish NEVER raises
on bad input — it returns a PolishResult with the original text on failure so
the caller can decide whether to ship the un-polished body or retry.

Methodology source: tianyayu6/fanqie-hit-short-story (MIT, 2026-06-17),
references/editorial-and-deai.md — delete / replace / preserve rules.
"""
from __future__ import annotations

import pytest

from fanqie_short_story.polish import (
    PolishResult,
    detect_ai_odor,
    run,
)
from fanqie_short_story.polish import _RULE_DELETE, _RULE_REPLACE


# ---------------------------------------------------------------------------
# Passthrough & data-shape
# ---------------------------------------------------------------------------


def test_run_intensity_0_is_passthrough() -> None:
    """intensity=0 must return the input unchanged — used by tests for
    A/B comparison and by callers that want deterministic behaviour."""
    text = "她如同潮水般涌来，情绪如同深渊无尽，光芒万丈。"  # 抽象比喻-laden
    res = run(text, intensity=0)
    assert isinstance(res, PolishResult)
    assert res.text == text
    assert res.intensity == 0
    assert res.rules_applied == []
    assert res.paragraphs_changed == 0


def test_polish_result_round_trips_json() -> None:
    """Manifest-side serialization must round-trip via dataclasses.asdict()
    so the caller can dump to JSON without bespoke logic."""
    from dataclasses import asdict
    res = run("hello", intensity=0)
    d = asdict(res)
    for required in ("text", "intensity", "ai_odor_score",
                     "rules_applied", "paragraphs_changed"):
        assert required in d, f"missing key: {required}"


# ---------------------------------------------------------------------------
# detect_ai_odor — heuristic scorer for intensity gating
# ---------------------------------------------------------------------------


def test_detect_ai_odor_returns_low_score_for_clean_prose() -> None:
    """Handwritten sentence (concrete objects + dialogue markers + short
    sentences) should score < 0.15 → intensity=1 would auto-downgrade to 0."""
    clean = (
        "我刚准备把婚书放回抽屉，外卖箱里传出一阵手机震动。\n"
        "我妈从厨房探出头：「谁啊？」\n"
        "「快递。」我合上录像带，把外卖单压在病历下面。"
    )
    score = detect_ai_odor(clean)
    assert 0.0 <= score < 0.15, f"clean prose should score low, got {score}"


def test_detect_ai_odor_returns_high_for_cliche_density() -> None:
    """Sentence full of 抽象比喻 (潮水/深渊/齿轮/光芒/牢笼) should score
    above 0.6 — triggers the gate that demands intensity≥1."""
    cliche = (
        "潮水般的情绪如同深渊一样将她吞没，光芒万丈的齿轮在牢笼中旋转，"
        "星辰与风暴在命运的画卷上交织成利刃。"
    )
    score = detect_ai_odor(cliche)
    assert score > 0.6, f"cliche-heavy text should score high, got {score}"


def test_detect_ai_odor_score_in_unit_interval() -> None:
    """Score must be 0.0..1.0 — caller relies on <0.15 and >0.6 thresholds."""
    for sample in ["", "干净短句。", "复杂的句子，包含一些潮水和星辰的比喻。",
                   "潮水 深渊 利刃 齿轮 牢笼 风暴 星辰 光芒 " * 10]:
        score = detect_ai_odor(sample)
        assert 0.0 <= score <= 1.0, f"score {score} out of range for {sample!r}"


# ---------------------------------------------------------------------------
# Rule tables — guard the catalogue
# ---------------------------------------------------------------------------


def test_rule_delete_table_is_non_empty_and_chinese_strings() -> None:
    """The delete rules must be Chinese strings (catalogue phrases the
    rule-based filter scans for in body text)."""
    assert _RULE_DELETE, "_RULE_DELETE must be populated"
    for rule in _RULE_DELETE:
        assert isinstance(rule, str)
        # At least one CJK character in each rule (no Latin-only placeholders).
        assert any("\u4e00" <= ch <= "\u9fff" for ch in rule), \
            f"non-CJK rule: {rule!r}"


def test_rule_replace_table_is_non_empty_and_chinese_strings() -> None:
    """Replace rules describe substitution patterns in plain Chinese so
    they're human-readable in error messages and audit logs."""
    assert _RULE_REPLACE, "_RULE_REPLACE must be populated"
    for rule in _RULE_REPLACE:
        assert isinstance(rule, str)
        assert any("\u4e00" <= ch <= "\u9fff" for ch in rule), \
            f"non-CJK rule: {rule!r}"


# ---------------------------------------------------------------------------
# intensity=1 — rule-based deletes (no LLM)
# ---------------------------------------------------------------------------


def test_run_intensity_1_removes_abstract_metaphors() -> None:
    """The 抽象比喻 cluster (潮水/深渊/齿轮/光芒/牢笼/风暴/星辰/利刃)
    is the #1 AI-odor signal. intensity=1 must strip it."""
    text = "她的心如潮水，思念如深渊，命运如齿轮般转动。"
    res = run(text, intensity=1)
    assert "潮水" not in res.text, f"abstract metaphor '潮水' should be removed; got: {res.text!r}"
    assert "深渊" not in res.text, f"abstract metaphor '深渊' should be removed; got: {res.text!r}"
    assert "齿轮" not in res.text, f"abstract metaphor '齿轮' should be removed; got: {res.text!r}"
    assert "intensity=1" in res.rules_applied or "delete_abstract_metaphor" in str(res.rules_applied) \
        or any("abstract" in r for r in res.rules_applied) \
        or len(res.rules_applied) > 0, f"no rule recorded in {res.rules_applied}"


def test_run_intensity_1_preserves_dialogue_punctuation() -> None:
    """Chinese punctuation (，。！？「」) must NOT be touched — those are
    the carrier of dialogue & sentence shape. (The 模板转折 phrase
    '谁也没想到' gets stripped; the surrounding punctuation must remain.)"""
    text = "她问：「你是谁，陌生人？」\n我回：「我……」\n——谁也没想到。"
    res = run(text, intensity=1)
    # All six punctuation marks must survive — they are the carrier of
    # dialogue shape and 番茄 readers parse on these glyphs.
    for keep in ("，", "。", "「", "」", "？", "……"):
        assert keep in res.text, f"punctuation {keep!r} must survive polish; got {res.text!r}"
    # '谁也没想到' gets stripped (one of the 模板转折 phrases), but the
    # surrounding em-dash and final period remain.
    assert "谁也没想到" not in res.text
    assert "——" in res.text


def test_run_intensity_1_does_not_split_one_sentence_per_line_by_default() -> None:
    """Default polish keeps paragraph form. The one-line mode is opt-in
    (called by the `--polish-one-line` CLI flag, not by default)."""
    text = "第一句。第二句！第三句？"
    res = run(text, intensity=1)
    # Body must stay as one paragraph (multiple sentences still on one line).
    assert "\n\n" not in res.text
    # At least one Chinese sentence terminator survives.
    assert any(t in res.text for t in ("。", "！", "？"))


# ---------------------------------------------------------------------------
# PolishResult invariants
# ---------------------------------------------------------------------------


def test_polish_result_ai_odor_score_in_unit_interval() -> None:
    """The ai_odor_score is used by the gate `if score<0.15 → skip polish`.
    Out-of-range scores would break the gate silently."""
    for intensity in (0, 1):
        res = run("潮水 深渊 光芒", intensity=intensity)
        assert 0.0 <= res.ai_odor_score <= 1.0, \
            f"intensity={intensity} produced score {res.ai_odor_score}"


def test_polish_never_raises_on_empty_or_garbage_input() -> None:
    """Polish is a post-processor; it must NEVER crash the pipeline even if
    the body is empty / only-whitespace / a single weird character."""
    for bad in ("", "   ", "\n\n\n", "🦀", None):
        try:
            res = run(bad, intensity=1)
            assert isinstance(res, PolishResult)
            assert isinstance(res.text, str)
        except Exception as e:
            pytest.fail(f"polish raised on {bad!r}: {e}")


# ---------------------------------------------------------------------------
# Edge case — polish.auto_bump_on_backtrack (plan-reviewer blocking #5)
# ---------------------------------------------------------------------------


def test_polish_run_with_none_intensity_uses_config_default() -> None:
    """Passing intensity=None must fall back to config.polish.default_intensity
    rather than crashing. Prevents caller-side `intensity or 1` footguns."""
    class _StubConfig:
        class polish:
            default_intensity = 2
    res = run("text", intensity=None, config=_StubConfig)
    assert res.intensity == 2, f"None intensity should default to config value; got {res.intensity}"
