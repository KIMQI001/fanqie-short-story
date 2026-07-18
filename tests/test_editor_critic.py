"""Tests for v0.4.0 llm_critique.py editor critic.

The legacy `llm_critique()` (5 flat LLM dimensions: 钩子/情节/人物/
节奏/语言) stays unchanged. v0.4.0 ADDS `llm_editor_critique()` that
uses 5 editor-perspective categories — each with surface vs structural
severity — and is structurally compatible with the pipeline backtrack
loop (Task 10).

Category-to-severity mapping (from spec §4.2):
  开篇 — structural on fail (weak opener breaks the 100-word hook)
  梗与题材 — structural on fail (no memory object = no tomato shelf-life)
  人物 — structural on fail (passive protagonist = no active choice)
  情绪兑现 — surface on fail (pacing can be re-tried within same outline)
  节奏 — surface on fail (same — re-roll body)

Methodology source: tianyayu6/fanqie-hit-short-story editorial-and-deai.md
(MIT, 2026-06-17), the 5 类别 审稿清单.
"""
from __future__ import annotations

import json
from typing import Callable

import pytest

from fanqie_short_story.body import Body
from fanqie_short_story.llm_critique import (
    CategoryVerdict,
    EditorReport,
    llm_editor_critique,
    _EDITOR_CATEGORIES,
    _STRUCTURAL_CATEGORIES,
)


# ---------------------------------------------------------------------------
# Catalogue + verdict dataclass sanity
# ---------------------------------------------------------------------------


def test_editor_categories_is_five_labels() -> None:
    """Five categories named in the methodology, in order."""
    assert isinstance(_EDITOR_CATEGORIES, list)
    assert len(_EDITOR_CATEGORIES) == 5
    expected = ("开篇", "梗与题材", "情绪兑现", "人物", "节奏")
    assert _EDITOR_CATEGORIES == list(expected)


def test_structural_categories_marked_correctly() -> None:
    """Three categories are structural (开篇/梗与题材/人物); two are surface
    (情绪兑现/节奏). Pinning this so a future edit can't accidentally
    reclassify and break the pipeline backtrack logic."""
    assert set(_STRUCTURAL_CATEGORIES) == {"开篇", "梗与题材", "人物"}


def test_category_verdict_is_dataclass_with_required_fields() -> None:
    """CategoryVerdict MUST be a dataclass with at least name/passed/notes/severity."""
    v = CategoryVerdict(name="开篇", passed=True, notes="", severity="structural")
    assert v.name == "开篇"
    assert v.passed is True
    assert v.notes == ""
    assert v.severity == "structural"


# ---------------------------------------------------------------------------
# EditorReport helpers
# ---------------------------------------------------------------------------


def test_editor_report_all_passed_when_every_category_passes() -> None:
    """all_passed is True iff every category.passed is True."""
    cats = [CategoryVerdict(name=n, passed=True, notes="", severity="structural")
            for n in _EDITOR_CATEGORIES]
    rep = EditorReport(categories=cats)
    assert rep.all_passed is True
    assert rep.structural_failure is False


def test_editor_report_structural_failure_set_when_structural_category_fails() -> None:
    """structural_failure is True iff any failed category has severity=='structural'."""
    cats = [
        CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="梗与题材", passed=False, notes="无记忆物件。",
                        severity="structural"),
        CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
        CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="节奏", passed=True, notes="", severity="surface"),
    ]
    rep = EditorReport(categories=cats)
    assert rep.all_passed is False
    assert rep.structural_failure is True


def test_editor_report_surface_failure_only_not_structural() -> None:
    """Failure on a surface-severity category doesn't count as structural."""
    cats = [
        CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
        CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="节奏", passed=False, notes="节奏偏慢。", severity="surface"),
    ]
    rep = EditorReport(categories=cats)
    assert rep.all_passed is False
    assert rep.structural_failure is False


# ---------------------------------------------------------------------------
# llm_editor_critique — happy paths + edge cases
# ---------------------------------------------------------------------------


def _editor_fake_llm(by_category: dict[str, dict]) -> Callable[..., str]:
    """Build a fake LLM that returns the JSON-encoded by_category mapping."""
    def fake_llm(prompt, **_kw):
        return json.dumps({"categories": by_category}, ensure_ascii=False)
    return fake_llm


def _config_stub() -> object:
    class _Cfg:
        critique = {"llm_max_tokens": 1000, "llm_temperature": 0.2}
    return _Cfg()


def test_editor_critic_returns_5_categories() -> None:
    body = Body.from_text("正文内容。")
    cfg = _config_stub()
    fake = _editor_fake_llm({
        n: {"passed": True, "notes": "", "severity": "structural" if n in _STRUCTURAL_CATEGORIES else "surface"}
        for n in _EDITOR_CATEGORIES
    })
    rep = llm_editor_critique(
        body=body, hook="x", genre="chuanqi", target_length=10000,
        llm=fake, config=cfg,
    )
    assert isinstance(rep, EditorReport)
    assert len(rep.categories) == 5
    # All passed → all_passed True; structural_failure False.
    assert rep.all_passed is True
    assert rep.structural_failure is False


def test_editor_critic_flags_structural_on_opener_failure() -> None:
    """开篇 fails with structural severity → structural_failure True."""
    body = Body.from_text("正文内容。")
    cfg = _config_stub()
    by_category = {
        "开篇": {"passed": False, "notes": "开篇 100 字无冲突。",
                 "severity": "structural"},
        "梗与题材": {"passed": True, "notes": "", "severity": "structural"},
        "情绪兑现": {"passed": True, "notes": "", "severity": "surface"},
        "人物": {"passed": True, "notes": "", "severity": "structural"},
        "节奏": {"passed": True, "notes": "", "severity": "surface"},
    }
    rep = llm_editor_critique(
        body=body, hook="x", genre="chuanqi", target_length=10000,
        llm=_editor_fake_llm(by_category), config=cfg,
    )
    assert rep.all_passed is False
    assert rep.structural_failure is True


def test_editor_critic_flags_structural_on_object_missing() -> None:
    """梗与题材 fails when there's no memory object → structural."""
    body = Body.from_text("正文")
    cfg = _config_stub()
    by_category = {
        "开篇": {"passed": True, "notes": "", "severity": "structural"},
        "梗与题材": {"passed": False, "notes": "无强记忆物件。",
                     "severity": "structural"},
        "情绪兑现": {"passed": True, "notes": "", "severity": "surface"},
        "人物": {"passed": True, "notes": "", "severity": "structural"},
        "节奏": {"passed": True, "notes": "", "severity": "surface"},
    }
    rep = llm_editor_critique(
        body=body, hook="x", genre="chuanqi", target_length=10000,
        llm=_editor_fake_llm(by_category), config=cfg,
    )
    assert rep.structural_failure is True


def test_editor_critic_treats_pacing_failure_as_surface() -> None:
    """节奏 fail → surface, NOT structural."""
    body = Body.from_text("正文")
    cfg = _config_stub()
    by_category = {
        "开篇": {"passed": True, "notes": "", "severity": "structural"},
        "梗与题材": {"passed": True, "notes": "", "severity": "structural"},
        "情绪兑现": {"passed": True, "notes": "", "severity": "surface"},
        "人物": {"passed": True, "notes": "", "severity": "structural"},
        "节奏": {"passed": False, "notes": "节奏过慢。", "severity": "surface"},
    }
    rep = llm_editor_critique(
        body=body, hook="x", genre="chuanqi", target_length=10000,
        llm=_editor_fake_llm(by_category), config=cfg,
    )
    assert rep.all_passed is False
    assert rep.structural_failure is False


def test_editor_critic_treats_emotional_payoff_as_surface() -> None:
    """情绪兑现 fail → surface."""
    body = Body.from_text("正文")
    cfg = _config_stub()
    by_category = {
        "开篇": {"passed": True, "notes": "", "severity": "structural"},
        "梗与题材": {"passed": True, "notes": "", "severity": "structural"},
        "情绪兑现": {"passed": False, "notes": "情绪兑现不足。", "severity": "surface"},
        "人物": {"passed": True, "notes": "", "severity": "structural"},
        "节奏": {"passed": True, "notes": "", "severity": "surface"},
    }
    rep = llm_editor_critique(
        body=body, hook="x", genre="chuanqi", target_length=10000,
        llm=_editor_fake_llm(by_category), config=cfg,
    )
    assert rep.structural_failure is False
    assert rep.all_passed is False


# ---------------------------------------------------------------------------
# JSON-fence + thinking-block handling (MiniMax quirks)
# ---------------------------------------------------------------------------


def test_editor_critic_parses_json_fence() -> None:
    """LLM wraps JSON in ```json … ``` fences — strip and parse."""
    body = Body.from_text("正文")
    cfg = _config_stub()
    payload = json.dumps({
        "categories": {
            n: {"passed": True, "notes": "", "severity": "structural" if n in _STRUCTURAL_CATEGORIES else "surface"}
            for n in _EDITOR_CATEGORIES
        }
    }, ensure_ascii=False)
    fenced = f"```json\n{payload}\n```"
    rep = llm_editor_critique(
        body=body, hook="x", genre="chuanqi", target_length=10000,
        llm=lambda *a, **kw: fenced, config=cfg,
    )
    assert rep.all_passed is True


def test_editor_critic_handles_missing_category_in_llm_output() -> None:
    """If the LLM omits a category, the editor critic MUST still return a
    5-category report — missing ones default to passed=False / surface
    so the pipeline doesn't crash."""
    body = Body.from_text("正文")
    cfg = _config_stub()
    # LLM only reports 3 of 5 categories.
    partial = json.dumps({"categories": {
        "开篇": {"passed": True, "notes": "", "severity": "structural"},
        "梗与题材": {"passed": True, "notes": "", "severity": "structural"},
        "情绪兑现": {"passed": True, "notes": "", "severity": "surface"},
    }}, ensure_ascii=False)
    rep = llm_editor_critique(
        body=body, hook="x", genre="chuanqi", target_length=10000,
        llm=lambda *a, **kw: partial, config=cfg,
    )
    assert len(rep.categories) == 5
    # Missing 人物 + 节奏 default to surface failure — surface count
    # should be ≥2 to confirm the gap-fill behaviour.
    missing = [c for c in rep.categories if not c.passed]
    assert len(missing) >= 2


def test_editor_critic_handles_completely_invalid_json() -> None:
    """If the LLM returns pure prose (no JSON), the editor critic MUST
    return all categories as passed=False — never raise."""
    body = Body.from_text("正文")
    cfg = _config_stub()
    rep = llm_editor_critique(
        body=body, hook="x", genre="chuanqi", target_length=10000,
        llm=lambda *a, **kw: "I think this is a great story. 5 stars.", config=cfg,
    )
    assert len(rep.categories) == 5
    assert rep.all_passed is False
    # All structural severities fail → structural_failure True.
    assert rep.structural_failure is True
