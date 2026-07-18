"""De-AI-flavor polish post-processor (v0.4.0).

Runs AFTER the editor critic accepts the body and BEFORE the manifest is
finalized. Three intensity levels:

  0 — no-op (passthrough; for tests + A/B comparison)
  1 — rule-based only (regex-driven deletion + substitution catalogue)
  2 — rule-based + one LLM pass for "替换" category
  3 — rule-based + full LLM restructure (mirrors tianyayu6 "rewrite" stage)

Polish NEVER raises on bad input — returns PolishResult with original text
when no work could be done, so the pipeline can ship an un-polished body
rather than crash. Methodology source: tianyayu6/fanqie-hit-short-story
(MIT, 2026-06-17), references/editorial-and-deai.md delete/replace/preserve.

Public surface:
    run(text, *, intensity=None, config=None) -> PolishResult
    detect_ai_odor(text) -> float  # 0.0..1.0 heuristic
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Rule catalogues
# ---------------------------------------------------------------------------

# Deletion rules — phrases the rule-based filter scans for and removes.
# Methodology source: tianyayu6 editorial-and-deai.md "删除" section,
# rephrased. The 第一类是空泛比喻 cluster is the #1 AI-odor signal on 番茄.
_RULE_DELETE: list[str] = [
    "抽象比喻：潮水/深渊/利刃/齿轮/牢笼/风暴/星辰/光芒",
    "抽象感慨：原来如此/我终于明白/命运真会开玩笑/这一刻我成长了",
    "重复心理：害怕/难过/心痛反复解释超过两次",
    "模板转折：谁也没想到/空气瞬间凝固/全场鸦雀无声/时间仿佛停止",
    "万能金句：迟来的深情比草贱/破镜不能重圆 (除非人物讽刺使用)",
]

# Replacement rules — describe substitution patterns in plain Chinese so
# they're human-readable in error messages and audit logs.
_RULE_REPLACE: list[str] = [
    "动作替代情绪：用具体动作（捏断笔帽/攥紧手指）替代'我很紧张'",
    "对话替代说明：让人物说出利益和威胁",
    "物件替代抒情：录音/外卖单/婚书/病历/弹幕截图/旧照片/转账记录",
    "小场景替代总结：结尾用动作，不写人生感悟",
]

# Preserve rules — short, dialogue-leaning prose is the goal; we MUST NOT
# strip these. Recorded for audit but not enforced by code.
_RULE_PRESERVE: list[str] = [
    "短句停顿口语",
    "不同人物不同说话习惯：权贵讲体面，家人讲亏欠，反派讲规矩",
    "反派偶尔说对一件事",
    "主角偶尔迟疑一次",
    "具体生活细节：电梯广告/群聊备注/外卖箱雨水/宴席座次/医院缴费单",
]


# Abstract-metaphor cluster — the single most important delete signal.
# Listed as a list (not a regex) so we can iterate it for rule-application
# audit trails. Order matters: longer phrases first (avoids partial matches).
_ABSTRACT_METAPHOR_TERMS: list[str] = [
    "潮水般", "如同潮水", "如潮水",
    "深渊", "万丈深渊", "无底深渊",
    "利刃", "锋利如刀",
    "齿轮", "齿轮般",
    "牢笼", "囚禁于",
    "风暴", "风暴骤起",
    "星辰", "漫天星辰",
    "光芒", "光芒万丈",
]

# Pre-compile single terms for fast path. Multi-word phrases stay as
# pre-compiled patterns so we keep the document readable.
_ABSTRACT_TERM_PATTERN = re.compile(
    "|".join(re.escape(t) for t in _ABSTRACT_METAPHOR_TERMS)
)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class PolishResult:
    """Outcome of a single polish run. Fields are JSON-serializable so
    callers can stash on manifest."""
    text: str
    intensity: int
    ai_odor_score: float
    rules_applied: list[str] = field(default_factory=list)
    paragraphs_changed: int = 0


# ---------------------------------------------------------------------------
# detect_ai_odor — heuristic gate
# ---------------------------------------------------------------------------

# Heuristic weights (sum to ~1.0 when all present so a worst-case sentence
# saturates at 1.0). Tuned conservatively; this is a gate, not a learned
# classifier. Real-world numbers tracked in plan §4.1.
def detect_ai_odor(text: str) -> float:
    """Heuristic 0.0..1.0 score based on:
      - density of abstract-metaphor vocabulary
      - density of 模板化转折 phrases (谁也没想到 / 空气凝固 / 时间仿佛停止)
      - density of 抽象感慨 phrases (原来如此 / 我终于明白)
      - average sentence length (very long sentences correlate with AI prose)

    Returns 0.0 for empty/whitespace input. Bounded to [0.0, 1.0].
    """
    if not text or not text.strip():
        return 0.0

    # Length-normalized term density.
    n_chars = max(len(text), 1)
    metaphor_hits = len(_ABSTRACT_TERM_PATTERN.findall(text))

    # 模板化转折 — separate compiled pattern.
    template_turns = re.findall(
        r"谁也没想到|空气瞬间凝固|全场鸦雀无声|时间仿佛停止|时间都静止了|空气都安静了",
        text,
    )

    # 抽象感慨 (resigned/reflective AI tells).
    abstract_feelings = re.findall(
        r"原来如此|我终于明白|命运真会开玩笑|这一刻我成长了",
        text,
    )

    # Sentence-length heuristic. AI tends toward uniformly long sentences
    # (≥40 chars between 。！？). Compute fraction of long sentences.
    sentences = [s for s in re.split(r"[。！？!?]", text) if s.strip()]
    if not sentences:
        long_sentence_ratio = 0.0
    else:
        long_sentence_ratio = sum(1 for s in sentences if len(s) >= 40) / len(sentences)

    raw = (
        (metaphor_hits * 0.10)         # metaphor cluster: most weight
        + (len(template_turns) * 0.20)  # 模板转折 phrases: rare, so high weight per occurrence
        + (len(abstract_feelings) * 0.15)
        + (long_sentence_ratio * 0.30)  # sentence-length can dominate
    )
    return min(1.0, raw)


# ---------------------------------------------------------------------------
# intensity=1 rule-based filter
# ---------------------------------------------------------------------------


def _apply_rule_based(text: str) -> tuple[str, list[str], int]:
    """Apply intensity=1 rules: remove abstract-metaphor cluster + 模板转折.

    Returns (new_text, rules_applied, paragraphs_changed).
    """
    rules_applied: list[str] = []
    paragraphs_changed = 0

    new_text = text
    for term in _ABSTRACT_METAPHOR_TERMS:
        if term in new_text:
            before = new_text
            new_text = new_text.replace(term, "")
            if new_text != before:
                paragraphs_changed += 1
    if paragraphs_changed:
        rules_applied.append("delete_abstract_metaphor")

    turn_changes = 0
    for turn in ("谁也没想到", "空气瞬间凝固", "全场鸦雀无声",
                 "时间仿佛停止", "时间都静止了", "空气都安静了"):
        if turn in new_text:
            before = new_text
            new_text = new_text.replace(turn, "")
            if new_text != before:
                turn_changes += 1
    if turn_changes:
        rules_applied.append("delete_template_turn")
        paragraphs_changed += turn_changes

    return new_text, rules_applied, paragraphs_changed


# ---------------------------------------------------------------------------
# run() — public entry point
# ---------------------------------------------------------------------------


def run(
    text: str | None,
    *,
    intensity: int | None = None,
    config: object | None = None,
) -> PolishResult:
    """Apply polish to `text` at the given intensity.

    Parameters
    ----------
    text : str | None
        Body text. None is treated as empty string (never raises).
    intensity : int | None
        0..3. None → fall back to config.polish.default_intensity, or 1.
    config : object | None
        Config-like object with `.polish.default_intensity` attribute.
        Duck-typed so tests don't need a real Config instance.

    Returns
    -------
    PolishResult
        Always. Never raises on bad/empty input.
    """
    safe_text = text if text is not None else ""

    # intensity resolution: explicit value wins, then config default, then 1.
    if intensity is None:
        try:
            intensity = int(config.polish.default_intensity)  # type: ignore[union-attr]
        except (AttributeError, TypeError, ValueError):
            intensity = 1
    intensity = max(0, min(3, int(intensity)))

    if intensity == 0 or not safe_text.strip():
        return PolishResult(
            text=safe_text,
            intensity=intensity,
            ai_odor_score=detect_ai_odor(safe_text),
            rules_applied=[],
            paragraphs_changed=0,
        )

    if intensity == 1:
        new_text, rules_applied, changed = _apply_rule_based(safe_text)
        return PolishResult(
            text=new_text,
            intensity=intensity,
            ai_odor_score=detect_ai_odor(new_text),
            rules_applied=rules_applied,
            paragraphs_changed=changed,
        )

    # intensity 2/3 — full LLM restructure (out of scope for v0.4.0 default;
    # gated by config.polish.full_llm=true in pipeline). Documented; current
    # implementation falls back to rule-based so we don't crash on misconfig.
    if intensity >= 2:
        new_text, rules_applied, changed = _apply_rule_based(safe_text)
        rules_applied.append("intensity_2_or_3_uses_rule_based_only_stub")
        return PolishResult(
            text=new_text,
            intensity=intensity,
            ai_odor_score=detect_ai_odor(new_text),
            rules_applied=rules_applied,
            paragraphs_changed=changed,
        )

    # Unreachable; included for type-narrowing.
    return PolishResult(
        text=safe_text,
        intensity=intensity,
        ai_odor_score=detect_ai_odor(safe_text),
        rules_applied=[],
        paragraphs_changed=0,
    )
