"""Critique: check 4 gates — hook / ending / length / POV. Lenient: all
heuristics are simple regex/string checks. False positives are OK; the
designer is a human, not the user."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from fanqie_short_story.body import Body


@dataclass
class CritiqueReport:
    passed: bool
    notes: list[str] = field(default_factory=list)
    failed_gates: list[str] = field(default_factory=list)


# Phrases that suggest a strong hook (presence of conflict, goal, mystery).
_HOOK_SIGNALS = (
    "撞见", "发现", "必须", "凶手", "重生", "穿越", "决裂", "翻脸",
    "杀了", "死", "血", "阴谋", "陷阱", "逼", "威胁", "对峙",
    "逃", "追", "破", "战", "斗", "反", "复仇", "讨", "恨", "惊",
)


_ENDING_FAIL_SIGNALS = (
    "未完待续", "请看下集", "请看下回", "下章揭晓",
    "to be continued", "...", "……",
)


def heuristic_critique(
    body: Body,
    hook: str,
    target_length: int,
    *,
    length_tolerance: float = 0.20,
    hook_window: int = 200,
    ending_window: int = 500,
    max_pov_switches: int = 3,
) -> CritiqueReport:
    notes: list[str] = []
    failed: list[str] = []

    # --- hook gate ---
    head = body.text[:hook_window]
    hook_hits = sum(1 for s in _HOOK_SIGNALS if s in head)
    if hook_hits < 2:
        failed.append("hook")
        notes.append(
            f"前 {hook_window} 字只检测到 {hook_hits} 个冲突信号词，"
            f"建议加强：冲突亮相 + 主角目标 + 钩子句。"
        )

    # --- ending gate ---
    tail = body.text[-ending_window:] if len(body.text) > ending_window else body.text
    if any(s in tail for s in _ENDING_FAIL_SIGNALS):
        failed.append("ending")
        notes.append(f"结尾 {ending_window} 字包含未收束信号词，必须改写收束。")

    # --- length gate ---
    low = target_length * (1 - length_tolerance)
    high = target_length * (1 + length_tolerance)
    if not (low <= body.char_count <= high):
        failed.append("length")
        notes.append(
            f"字数 {body.char_count} 不在目标 {target_length} 的 "
            f"±{int(length_tolerance * 100)}% 窗口内 ({int(low)}-{int(high)})。"
        )

    # --- POV gate ---
    # Crude heuristic: in a body that's supposed to be 主角-pov, sudden
    # appearances of "我" with POV-action verbs signal a flip.
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
