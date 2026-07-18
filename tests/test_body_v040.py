"""Tests for v0.4.0 body.py extensions.

The system prompt that goes to the LLM gets 5 新硬约束 appended when
the outline has chapters (v0.4.0 tomato methodology density rules).

Methodology source: tianyayu6/fanqie-hit-short-story methodology.md —
"番茄爆款短篇硬约束（已写入大纲后仍然强制）":
1. 开篇前 100 字必须直入冲突
2. 每章开头 3-5 句必须进入本章冲突
3. 每 600-800 字至少出现一个：场景/动作变化/对话压力/信息反转
4. 每章结尾留一句新信息、新危机或情绪落点（钩子）
5. 主角每章至少一次主动选择（签/走/录/问/拒/公开）
6. 至少一个具体物件串起真相
禁止：抽象比喻 + 模板转折.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fanqie_short_story.body import (
    DENSITY_RULES,
    FORBIDDEN_CLICHES,
    _build_system_prompt,
    generate_body,
)
from fanqie_short_story.outline import (
    CHAPTER_TEMPLATE,
    ChapterSpec,
    Outline,
)


# ---------------------------------------------------------------------------
# Density rules catalogue — sanity-check the strings before they ship
# ---------------------------------------------------------------------------


def test_density_rules_are_six_chinese_bullets() -> None:
    """Five density constraints + one object constraint = six bullets.
    Each must be a non-empty string with at least one CJK glyph."""
    assert isinstance(DENSITY_RULES, list)
    assert len(DENSITY_RULES) >= 5, f"expected ≥5 density rules; got {len(DENSITY_RULES)}"
    for rule in DENSITY_RULES:
        assert isinstance(rule, str) and rule.strip()
        assert any("\u4e00" <= ch <= "\u9fff" for ch in rule), \
            f"non-CJK rule: {rule!r}"


def test_forbidden_cliches_list_includes_top_signals() -> None:
    """The two clusters (抽象比喻 + 模板转折) MUST be in the forbidden
    list — they're the #1 AI-odor signals per the methodology."""
    blob = "\n".join(FORBIDDEN_CLICHES)
    # 抽象比喻 cluster — every term must be enumerated.
    for term in ("潮水", "深渊", "利刃", "齿轮", "牢笼", "风暴", "星辰", "光芒"):
        assert term in blob, f"forbidden cluster missing {term!r}"
    # 模板转折 cluster.
    for term in ("谁也没想到", "空气瞬间凝固", "全场鸦雀无声", "时间仿佛停止"):
        assert term in blob, f"forbidden cluster missing {term!r}"


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


def _outline_with_chapters() -> Outline:
    return Outline(
        title_seed="测试",
        beats=[],
        chapters=[
            ChapterSpec(index=i + 1, title=t, core_event=f"事件{i + 1}",
                        emotional_value="爽", hook_at_ending=f"钩子{i + 1}")
            for i, (t, _hint) in enumerate(CHAPTER_TEMPLATE)
        ],
        mood_axis=("爽", None),
    )


def test_build_system_prompt_appends_density_rules_when_chapters_present() -> None:
    """When the outline has chapters (v0.4.0), the system prompt MUST
    end with the density-constraint block. Without it, the LLM produces
    AI-odor prose regardless of the outline context."""
    out = _outline_with_chapters()
    prompt = _build_system_prompt(out)
    for rule in DENSITY_RULES:
        assert rule in prompt, f"density rule missing from system prompt: {rule!r}"
    # Banned phrases must appear as negative instructions.
    for term in ("潮水", "深渊", "谁也没想到", "空气瞬间凝固"):
        assert term in prompt, f"forbidden term {term!r} missing from system prompt"


def test_build_system_prompt_omits_density_rules_when_no_chapters() -> None:
    """When outline has no chapters (legacy v0.3.x caller), the system
    prompt stays close to the legacy BODY_SYSTEM — DON'T append density
    rules that don't apply to short universal prompts."""
    legacy_outline = Outline(title_seed="legacy", beats=["事件1"])
    prompt = _build_system_prompt(legacy_outline)
    # Density rules are NOT injected when chapters list is empty.
    assert "100 字" not in prompt, "density rule '100 字' leaked into legacy prompt"
    assert "潮水" not in prompt, "forbidden cluster leaked into legacy prompt"


def test_build_system_prompt_includes_mood_axis() -> None:
    """The system prompt embeds the mood axis so the LLM calibrates tone:
    '主情绪：爽' must appear when mood_axis=('爽', None)."""
    out = _outline_with_chapters()
    prompt = _build_system_prompt(out)
    assert "爽" in prompt, "mood major '爽' missing from system prompt"
    # minor=None shouldn't print literally 'None' (render as '无' or '-').
    assert "无" in prompt or "—" in prompt or "（无）" in prompt, \
        "no-mood-minor marker missing"


# ---------------------------------------------------------------------------
# generate_body — density rules reach LLM
# ---------------------------------------------------------------------------


def test_generate_body_injects_density_rules_when_chapters_present() -> None:
    """generate_body must call the LLM with a system prompt that contains
    the tomato density rules when given a chaptered Outline."""
    out = _outline_with_chapters()
    captured: dict = {}
    def fake_llm(prompt, *, config, max_tokens, temperature, system):
        captured["system"] = system
        captured["prompt"] = prompt
        return "开头直接进入冲突。第一章正文。"

    config = MagicMock()
    config.body = {"default_max_tokens": 20000, "default_temperature": 0.7}
    body = generate_body(
        outline=out, hook="退婚后我当场签字", genre="chuanqi",
        target_length=12000, tone="sweet_with_suspense",
        llm=fake_llm, config=config,
    )
    assert isinstance(body.text, str)
    assert "潮水" in captured["system"], \
        "forbidden cluster '潮水' must be in system prompt sent to LLM"
    assert "100 字" in captured["system"], \
        "opening-100-words rule must be in system prompt"
