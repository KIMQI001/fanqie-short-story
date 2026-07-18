"""LLM-based critic (v0.3.x kept + v0.4.0 editor critic).

Augments the heuristic critique with a deeper LLM-driven review.

v0.3.x — `llm_critique()` — flat 5-aspect narrative review
  钩子 / 情节 / 人物 / 节奏 / 语言
  Returns LLMCritiqueReport (passed, notes, mentioned_aspects, raw).
  Used by the v0.3.x pipeline.

v0.4.0 ADD — `llm_editor_critique()` — 5-category editor-perspective review
  开篇 / 梗与题材 / 情绪兑现 / 人物 / 节奏
  Each category carries a severity: "structural" (must backtrack to
  outline) or "surface" (retry body with feedback). Structural failures
  trip the pipeline's outline-backtrack cap (see pipeline.py v0.4.0).
  Returns EditorReport (categories, all_passed, structural_failure).

Methodology source: tianyayu6/fanqie-hit-short-story editorial-and-deai.md
(MIT, 2026-06-17), the 5 类别 审稿清单.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fanqie_short_story.body import Body, _strip_json_fences
from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm
from fanqie_short_story.prompts import LLM_CRITIQUE_SYSTEM, LLM_CRITIQUE_USER_TEMPLATE


_VERDICT_RE = re.compile(r"verdict\s*[:：]\s*(pass|fail)\b", re.IGNORECASE)

_ASPECT_TERMS = ("钩子", "情节", "人物", "节奏", "语言")


# ---------------------------------------------------------------------------
# Legacy v0.3.x LLMCritiqueReport (unchanged)
# ---------------------------------------------------------------------------


@dataclass
class LLMCritiqueReport:
    passed: bool
    notes: str                              # full prose; always populated (sentinel on empty response)
    mentioned_aspects: list[str] = field(default_factory=list)
    raw_response: str = ""


def _parse_verdict(text: str) -> tuple[bool, str]:
    """Find VERDICT line bottom-up. Returns (passed, full_prose).

    No VERDICT line → (False, full_prose) defensive.
    Full-width colon tolerated.
    Empty response → (False, "(empty critic response)") per spec §5.3.
    """
    cleaned = _strip_json_fences(text).strip()
    if not cleaned:
        return False, "(empty critic response)"
    for line in reversed(cleaned.splitlines()):
        m = _VERDICT_RE.search(line)
        if m:
            return m.group(1).lower() == "pass", cleaned
    return False, cleaned


def _extract_mentioned_aspects(text: str) -> list[str]:
    return [term for term in _ASPECT_TERMS if term in text]


def llm_critique(
    body: Body,
    hook: str,
    genre: str,
    target_length: int,
    *,
    llm: Callable[..., str] = call_llm,
    config: Config,
) -> LLMCritiqueReport:
    prompt = LLM_CRITIQUE_USER_TEMPLATE.format(
        hook=hook, genre=genre, target_length=target_length, body=body.text,
    )
    raw = llm(
        prompt,
        config=config,
        max_tokens=config.critique.get("llm_max_tokens", 2000),
        temperature=config.critique.get("llm_temperature", 0.3),
        system=LLM_CRITIQUE_SYSTEM,
    )
    passed, prose = _parse_verdict(raw)
    return LLMCritiqueReport(
        passed=passed,
        notes=prose,
        mentioned_aspects=[] if passed else _extract_mentioned_aspects(prose),
        raw_response=raw,
    )


# ---------------------------------------------------------------------------
# v0.4.0 EditorReport + llm_editor_critique
# ---------------------------------------------------------------------------


# Five editor-perspective categories in the methodology order. Order matters
# — the EditorReport renders categories in this order.
_EDITOR_CATEGORIES: list[str] = ["开篇", "梗与题材", "情绪兑现", "人物", "节奏"]

# Three of the five are STRUCTURAL — they require outline regeneration,
# not a body re-roll. The other two are SURFACE — the body just needs
# more feedback.
_STRUCTURAL_CATEGORIES: set[str] = {"开篇", "梗与题材", "人物"}

_EDITOR_SYSTEM = (
    "你是 番茄爆款短篇 编辑审稿人。"
    "对给定 5 个类别（开篇 / 梗与题材 / 情绪兑现 / 人物 / 节奏）"
    "逐一判定 pass / fail，给一句话观察（fail 时）；severity 为 "
    "'structural' 或 'surface'。STRICT JSON 输出，无解释、无 markdown 围栏。"
    "severity 规则：开篇/梗与题材/人物 = structural；"
    "情绪兑现/节奏 = surface。仅当确实需要重新打大纲时才用 structural。"
)

_EDITOR_USER_TEMPLATE = """钩子: {hook}
类型: {genre}
目标字数: {target_length}

## 5 类别审稿
逐一对以下五个类别给出 pass/fail + 一句观察 + severity（structural / surface）：
- 开篇 (前 100 字必须直入冲突)
- 梗与题材 (核心梗一句话讲得清 + 至少 1 个记忆物件：录像带/婚书/病历/亲子鉴定/倒计时/账本/弹幕/外卖单/旧照片/转账记录)
- 情绪兑现 (爽文每 1-2 章 1 小爽点 / 虐文误会→证据→迟来崩溃 / 甜宠明确偏爱 / 沙雕误会滚雪球)
- 人物 (主角每章至少 1 次主动选择 + 反派有具体压迫)
- 节奏 (每章开头 3-5 句进入冲突 + 章末留钩子 + 每 600-800 字 1 处变化)

## 正文
{body}

严格 JSON 输出，格式：
{{"categories": {{"<类别>": {{"passed": true/false, "notes": "一句话", "severity": "structural/surface"}}, ...}}}}

只输出 JSON 对象。"""


@dataclass
class CategoryVerdict:
    """One editor category's pass/fail + one-line observation + severity."""
    name: str                              # one of _EDITOR_CATEGORIES
    passed: bool
    notes: str                             # empty when passed; observation when failed
    severity: str                          # "structural" | "surface"


@dataclass
class EditorReport:
    """Result of `llm_editor_critique`. Composed of 5 CategoryVerdict
    entries plus two derived properties used by the pipeline.
    """
    categories: list[CategoryVerdict]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.categories)

    @property
    def structural_failure(self) -> bool:
        return any((not c.passed) and c.severity == "structural" for c in self.categories)


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """Pull a JSON object out of an LLM response that may have prose /
    fences / extra commentary. Returns None on failure."""
    if not text:
        return None
    cleaned = _strip_json_fences(text)
    # Try direct parse.
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except (ValueError, json.JSONDecodeError):
        pass
    # Try fence-extract.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        try:
            data = json.loads(fence.group(1))
            if isinstance(data, dict):
                return data
        except (ValueError, json.JSONDecodeError):
            pass
    # Try bracket-extract (first `{` to last `}`).
    if "{" in cleaned and "}" in cleaned:
        fragment = cleaned[cleaned.index("{"):cleaned.rindex("}") + 1]
        try:
            data = json.loads(fragment)
            if isinstance(data, dict):
                return data
        except (ValueError, json.JSONDecodeError):
            pass
    return None


def _gap_fill_missing(cats: dict[str, CategoryVerdict]) -> EditorReport:
    """Ensure all 5 categories are present; missing ones default to
    passed=False / surface so the pipeline doesn't crash on a partial
    LLM response."""
    out: list[CategoryVerdict] = []
    for name in _EDITOR_CATEGORIES:
        if name in cats:
            out.append(cats[name])
        else:
            out.append(CategoryVerdict(
                name=name,
                passed=False,
                notes="（LLM 未给出该类别判定，按未通过处理）",
                severity="surface" if name not in _STRUCTURAL_CATEGORIES else "structural",
            ))
    return EditorReport(categories=out)


def llm_editor_critique(
    body: Body,
    hook: str,
    genre: str,
    target_length: int,
    *,
    llm: Callable[..., str] = call_llm,
    config: Any,
) -> EditorReport:
    """5-category editor critic. Returns EditorReport with `all_passed`
    and `structural_failure` properties.

    Robust against:
      - JSON fences (```json … ```)
      - prose-wrapped JSON ("Sure! Here it is: {…}")
      - partial LLM output (missing categories default to passed=False)
      - completely invalid JSON (all categories default to passed=False
        with severity per the catalogue)
    """
    prompt = _EDITOR_USER_TEMPLATE.format(
        hook=hook, genre=genre, target_length=target_length, body=body.text,
    )
    raw = llm(
        prompt,
        config=config,
        max_tokens=config.critique.get("llm_max_tokens", 2000)
                     if hasattr(config, "critique") else 2000,
        temperature=config.critique.get("llm_temperature", 0.3)
                     if hasattr(config, "critique") else 0.3,
        system=_EDITOR_SYSTEM,
    )

    parsed = _extract_json_object(raw)
    if not parsed or "categories" not in parsed or not isinstance(parsed["categories"], dict):
        # Fallback: all categories failed (so the pipeline retries).
        cats_list: list[CategoryVerdict] = []
        for name in _EDITOR_CATEGORIES:
            cats_list.append(CategoryVerdict(
                name=name,
                passed=False,
                notes="（LLM 返回无法解析）",
                severity="structural" if name in _STRUCTURAL_CATEGORIES else "surface",
            ))
        return EditorReport(categories=cats_list)

    cats: dict[str, CategoryVerdict] = {}
    for name, info in parsed["categories"].items():
        if name not in _EDITOR_CATEGORIES:
            continue
        if not isinstance(info, dict):
            info = {"passed": False, "notes": "(malformed)", "severity": "surface"}
        passed = bool(info.get("passed", False))
        notes = str(info.get("notes", "")).strip()
        severity = str(info.get("severity", "surface")).strip().lower()
        if severity not in ("structural", "surface"):
            severity = "surface"
        cats[name] = CategoryVerdict(
            name=name, passed=passed, notes=notes, severity=severity,
        )
    return _gap_fill_missing(cats)
