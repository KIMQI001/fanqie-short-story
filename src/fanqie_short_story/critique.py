"""Critique: check 4 gates — hook / ending / length / POV. Lenient: all
heuristics are simple regex/string checks. False positives are OK; the
designer is a human, not the user.

v0.4.0 ADDS the 6-item 写作禁区 (writing-forbidden) rules. They are
additive — exposed as a SEPARATE function `writing_forbidden_critique()`
so callers can opt-in independently of the v0.3.x 4-gate heuristic.
`combined_heuristic_critique()` runs both passes and merges failures.

Defaults are LOOSE for v0.3.3 onward. The strict v0.1.0 defaults (length
±20%, pov >3, hook ≥2) were calibrated against a hand-picked hook
fixture; against open-ended daily hooks the LLM produces bodies that
hit only 0-1 of the 26 hard-coded hook signal phrases, undershoot the
length target by 30-50%, and routinely use 4-7 POV-action verb matches.
The v0.3.2 e2e diagnostic showed the strict defaults reject ~70% of
real LLM bodies. Pass explicit kwargs to recover strict behavior.

Methodology source: tianyayu6/fanqie-hit-short-story methodology.md
(MIT, 2026-06-17), 6-item 写作禁区 list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from fanqie_short_story.body import Body


# ---------------------------------------------------------------------------
# v0.3.x CritiqueReport + 4-gate heuristic (unchanged)
# ---------------------------------------------------------------------------


@dataclass
class CritiqueReport:
    passed: bool
    notes: list[str] = field(default_factory=list)
    failed_gates: list[str] = field(default_factory=list)


_HOOK_SIGNALS = (
    "撞见", "发现", "必须", "凶手", "重生", "穿越", "决裂", "翻脸",
    "杀了", "死", "血", "阴谋", "陷阱", "逼", "威胁", "对峙",
    "逃", "追", "破", "战", "斗", "反", "复仇", "讨", "恨", "惊",
)


_ENDING_FAIL_SIGNALS = (
    "未完待续", "请看下集", "请看下回", "下章揭晓", "to be continued",
)


def heuristic_critique(
    body: Body,
    hook: str,
    target_length: int,
    *,
    length_tolerance: float = 0.50,
    hook_window: int = 200,
    ending_window: int = 500,
    max_pov_switches: int = 8,
    min_hook_signals: int = 1,
) -> CritiqueReport:
    notes: list[str] = []
    failed: list[str] = []

    head = body.text[:hook_window]
    hook_hits = sum(1 for s in _HOOK_SIGNALS if s in head)
    if hook_hits < min_hook_signals:
        failed.append("hook")
        notes.append(
            f"前 {hook_window} 字只检测到 {hook_hits} 个冲突信号词，"
            f"建议加强：冲突亮相 + 主角目标 + 钩子句。"
        )

    tail = body.text[-ending_window:] if len(body.text) > ending_window else body.text
    if any(s in tail for s in _ENDING_FAIL_SIGNALS):
        failed.append("ending")
        notes.append(f"结尾 {ending_window} 字包含未收束信号词，必须改写收束。")

    low = target_length * (1 - length_tolerance)
    high = target_length * (1 + length_tolerance)
    if not (low <= body.char_count <= high):
        failed.append("length")
        notes.append(
            f"字数 {body.char_count} 不在目标 {target_length} 的 "
            f"±{int(length_tolerance * 100)}% 窗口内 ({int(low)}-{int(high)})。"
        )

    if "我" in body.text and re.search(r"我[转身走向跑看听闻说想]", body.text):
        switches = len(re.findall(r"我[转身走向跑看听闻说想]", body.text))
        if switches > max_pov_switches:
            failed.append("pov")
            notes.append(f"POV 切换 {switches} 次，超过阈值 {max_pov_switches}。")

    return CritiqueReport(
        passed=len(failed) == 0,
        notes=notes,
        failed_gates=failed,
    )


# ---------------------------------------------------------------------------
# v0.4.0: 6 写作禁区 (writing-forbidden) rules + WritingForbiddenReport
# ---------------------------------------------------------------------------


@dataclass
class WritingForbiddenReport:
    """Outcome of the 写作禁区 rule pass."""
    passed: bool
    failed_rules: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# (rule_name, detector_callable_returning_Optional[str]) tuples. The detector
# returns a note string when the rule fires, or None when the body is clean.
def _check_weather_or_dream_opener(body: Body) -> str | None:
    """前 100 字出现天气/梦境/身世/世界设定 → fail."""
    head = body.text[:100]
    signals = ("阳光", "夜色", "月光", "梦里", "醒来", "身世", "世界",
               "大陆", "传说", "很久以前", "从前有个")
    for s in signals:
        if s in head:
            return (
                f"开篇前 100 字出现写作禁区信号「{s}」；"
                f"必须前 100 字直入冲突（事故/退婚/弹幕预警/公开审判等）。"
            )
    return None


def _check_three_paragraph_monologue(body: Body) -> str | None:
    """3 段及以上连续心理独白（每段都出现「我想」类 marker）→ fail."""
    paragraphs = [p for p in re.split(r"\n\s*\n", body.text) if p.strip()]
    monologue_markers = ("我想", "我觉得", "我想起", "我感到", "我在想")
    consecutive = 0
    longest = 0
    for p in paragraphs:
        if any(m in p for m in monologue_markers):
            consecutive += 1
            longest = max(longest, consecutive)
        else:
            consecutive = 0
    if longest >= 3:
        return (
            f"检测到连续 {longest} 段心理独白；写作禁区规定最多 1-2 段独白，"
            f"其余段落用动作/对话/物件替代。"
        )
    return None


def _check_abstract_metaphor_cliche(body: Body) -> str | None:
    """Body 包含 抽象比喻 cluster (潮水/深渊/利刃/齿轮/牢笼/风暴/星辰/光芒) → fail."""
    terms = ("潮水", "深渊", "利刃", "齿轮", "牢笼", "风暴", "星辰", "光芒")
    hits = [t for t in terms if t in body.text]
    if hits:
        return (
            f"使用写作禁区中的空泛比喻 ({' / '.join(hits)})；"
            f"用具体物件/动作替代（婚书、外卖单、病历、亲子鉴定等）。"
        )
    return None


def _check_twist_without_setup(body: Body) -> str | None:
    """大反转前 2000 字内无物证/规则/言行伏笔 → fail. Detected by looking
    for a 真相型 marker in the last 2000 chars preceded by no concrete
    object in the previous 2000 chars."""
    truth_markers = ("真相是", "原来，", "实际是", "实际上", "这一切都是")
    body_text = body.text
    for marker in truth_markers:
        idx = body_text.rfind(marker)
        if idx == -1:
            continue
        preceding = body_text[max(0, idx - 2000):idx]
        objects = ("录像带", "婚书", "病历", "亲子鉴定", "账本",
                   "外卖单", "旧照片", "转账记录", "弹幕截图", "遗诏", "玉佩")
        if not any(obj in preceding for obj in objects):
            return (
                f"大反转（前 2000 字内「{marker}」）前 2000 字无物证伏笔；"
                f"写作禁区要求大反转前必须有具体物件/规则/言行伏笔。"
            )
    return None


def _check_missing_memory_object(body: Body) -> str | None:
    """全文未出现强记忆物件 → fail."""
    objects = ("录像带", "婚书", "病历", "亲子鉴定", "倒计时", "账本",
               "弹幕截图", "外卖单", "旧照片", "转账记录", "遗诏", "玉佩")
    if not any(obj in body.text for obj in objects):
        return (
            "全文未出现强记忆物件（录像带/婚书/病历/亲子鉴定/倒计时/账本/"
            "弹幕截图/外卖单/旧照片/转账记录）；写作禁区要求至少一个物件串起真相。"
        )
    return None


def _check_passive_protagonist(body: Body) -> str | None:
    """Heuristic for 全程被动 chapter — body has ≥10 paragraphs with NO
    active-verb markers (签/走/录/问/拒/公开/按/写). Lenient: only fires
    when the active-verb density is <0.5/paragraph."""
    paragraphs = [p for p in re.split(r"\n\s*\n", body.text) if p.strip()]
    if len(paragraphs) < 3:
        return None
    active_markers = ("我签", "我走", "我录", "我问", "我拒",
                      "我公开", "我按", "我写", "我撕", "我抓", "我打", "我收")
    inactive_count = sum(1 for p in paragraphs
                         if not any(m in p for m in active_markers))
    if inactive_count >= max(8, len(paragraphs) // 2):
        return (
            f"{inactive_count} / {len(paragraphs)} 段未检测到主角主动动作；"
            f"写作禁区要求每章至少一次主动选择（签/走/录/问/拒/公开等）。"
        )
    return None


# Public catalogue — 6 named rules, order is significant (test asserts count).
# Each name includes a Chinese display label so audit logs read in 中文.
FORBIDDEN_WRITE_PATTERNS: list[tuple[str, Callable]] = [  # type: ignore[type-arg]
    ("写作禁区_weather_or_dream_opener", _check_weather_or_dream_opener),
    ("写作禁区_three_paragraph_monologue", _check_three_paragraph_monologue),
    ("写作禁区_abstract_metaphor_cliche", _check_abstract_metaphor_cliche),
    ("写作禁区_passive_protagonist_full_chapter", _check_passive_protagonist),
    ("写作禁区_twist_without_setup", _check_twist_without_setup),
    ("写作禁区_missing_memory_object", _check_missing_memory_object),
]


def writing_forbidden_critique(body: Body) -> WritingForbiddenReport:
    """Run all 6 写作禁区 detectors over the body. Each is independent;
    all 6 are checked (not short-circuited) so a body can be reported as
    failing multiple rules in a single pass."""
    failed: list[str] = []
    notes: list[str] = []
    for name, detector in FORBIDDEN_WRITE_PATTERNS:
        note = detector(body)
        if note is not None:
            failed.append(name)
            # Prefix note with the rule name so audit logs identify the
            # offending rule by human-readable label.
            notes.append(f"[{name}] {note}")
    return WritingForbiddenReport(
        passed=len(failed) == 0,
        failed_rules=failed,
        notes=notes,
    )


def combined_heuristic_critique(
    body: Body,
    hook: str,
    target_length: int,
    *,
    length_tolerance: float = 0.50,
    hook_window: int = 200,
    ending_window: int = 500,
    max_pov_switches: int = 8,
    min_hook_signals: int = 1,
) -> CritiqueReport:
    """Run the v0.3.x 4-gate heuristic AND the v0.4.0 6-item 写作禁区
    check; merge failures into a single CritiqueReport. Returns notes
    prefixed with `[gate]` or `[禁区]` so callers can distinguish."""
    base = heuristic_critique(
        body=body, hook=hook, target_length=target_length,
        length_tolerance=length_tolerance, hook_window=hook_window,
        ending_window=ending_window, max_pov_switches=max_pov_switches,
        min_hook_signals=min_hook_signals,
    )
    forbidden = writing_forbidden_critique(body)
    merged_failed = list(base.failed_gates)
    merged_notes = [f"[gate] {n}" for n in base.notes]
    for rule, note in zip(forbidden.failed_rules, forbidden.notes):
        merged_failed.append(f"禁区:{rule}")
        merged_notes.append(f"[禁区] {note}")
    return CritiqueReport(
        passed=base.passed and forbidden.passed,
        notes=merged_notes,
        failed_gates=merged_failed,
    )
