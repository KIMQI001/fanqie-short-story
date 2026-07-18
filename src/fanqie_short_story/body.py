"""Body generator: Outline + hook + length → Body (plain text, 1-3万字).

v0.4.0 EXTENDS the system prompt with the tomato-methodology density
constraint block (DENSITY_RULES) and the forbidden-cliché block
(FORBIDDEN_CLICHES) whenever the Outline has `chapters` populated.
The legacy BODY_SYSTEM is preserved for v0.3.x callers whose Outline
has no chapters — they get the old behaviour exactly.

Methodology source: tianyayu6/fanqie-hit-short-story methodology.md
(MIT, 2026-06-17), "番茄爆款短篇硬约束（已写入大纲后仍然强制）".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm as default_llm
from fanqie_short_story.outline import Outline
from fanqie_short_story.prompts import BODY_SYSTEM, BODY_USER_TEMPLATE


# ---------------------------------------------------------------------------
# v0.4.0: tomato density rules + forbidden-cliché blocks
# ---------------------------------------------------------------------------


DENSITY_RULES: list[str] = [
    "开篇前 100 字必须直入冲突，不写天气/梦境/身世/世界设定。",
    "每章开头 3-5 句必须进入本章冲突。",
    "每 600-800 字至少一个：场景/动作变化/对话压力/信息反转。",
    "每章结尾留一句新信息、新危机或情绪落点（钩子）。",
    "主角每章至少一次主动选择（签/走/录/问/拒/公开）。",
    "至少一个具体物件串起真相（婚书/病历/亲子鉴定/录音/弹幕截图/外卖单/旧照片/转账记录/账本/倒计时）。",
]


# Forbidden cluster — the 抽象比喻 eight + 模板转折 four. The
# methodology treats these as AI-odor tells; we list them as
# negative instructions in the system prompt so the LLM actively
# avoids them.
FORBIDDEN_CLICHES: list[str] = [
    "抽象比喻：禁止使用 潮水 / 深渊 / 利刃 / 齿轮 / 牢笼 / 风暴 / 星辰 / 光芒 等空泛比喻。",
    "模板转折：禁止使用 谁也没想到 / 空气瞬间凝固 / 全场鸦雀无声 / 时间仿佛停止 等转折套语。",
    "抽象感慨：禁止使用 原来如此 / 我终于明白 / 命运真会开玩笑 / 这一刻我成长了 等直接抒发。",
]


@dataclass
class Body:
    text: str
    char_count: int

    @classmethod
    def from_text(cls, text: str) -> "Body":
        # Chinese char count: drop whitespace, count remaining.
        stripped = re.sub(r"\s+", "", text)
        return cls(text=text, char_count=len(stripped))


def _strip_json_fences(text: str) -> str:
    """Some MiniMax responses wrap output in ```json ... ``` even for plain
    text. Strip fences and surrounding chatter to get the real body."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:[a-z]*\n)?", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# v0.4.0: extractable system-prompt builder
# ---------------------------------------------------------------------------


def _build_system_prompt(outline: Outline | None) -> str:
    """Compose the LLM system prompt. Legacy v0.3.4 prompt when the
    outline has no chapters; v0.4.0 prompt + density rules + forbidden
    cluster + mood-axis when chapters are populated.

    Extracted from generate_body() so tests can introspect it without
    mocking the LLM.
    """
    if outline is None or not outline.chapters:
        return BODY_SYSTEM

    major = outline.mood_axis[0] if outline and outline.mood_axis else "爽"
    minor = outline.mood_axis[1] if outline and outline.mood_axis and len(outline.mood_axis) > 1 else None
    minor_text = minor if minor else "无"

    density_block = "\n".join(f"- {r}" for r in DENSITY_RULES)
    forbidden_block = "\n".join(f"- {r}" for r in FORBIDDEN_CLICHES)

    return (
        BODY_SYSTEM
        + "\n\n## 番茄爆款短篇硬约束（已写入大纲后仍然强制）\n"
        + density_block
        + "\n\n## 禁止使用\n"
        + forbidden_block
        + f"\n\n## 情绪轴\n- 主情绪：{major}\n- 副情绪：{minor_text}"
    )


def generate_body(
    outline: Outline,
    hook: str,
    genre: str,
    target_length: int,
    tone: str,
    *,
    critique_feedback: list[str] | None = None,
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> Body:
    critique_block = ""
    if critique_feedback:
        joined = "\n".join(f"- {n}" for n in critique_feedback)
        critique_block = f"## 上一版问题（必须修正）\n{joined}\n"
    prompt = BODY_USER_TEMPLATE.format(
        hook=hook, genre=genre, target_length=target_length, tone=tone,
        outline=outline.to_prompt_string(), critique_block=critique_block,
    )
    system_prompt = _build_system_prompt(outline)
    if config is not None:
        raw = llm(
            prompt,
            config=config,
            max_tokens=config.body.get("default_max_tokens", 20000),
            temperature=config.body.get("default_temperature", 0.7),
            system=system_prompt,
        )
    else:
        raw = llm(prompt)
    return Body.from_text(_strip_json_fences(raw))
