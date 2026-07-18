"""Outline generator: hook + genre + length + tone + mood → Outline.

The v0.3.4 parser accepted markdown with sections 幕 / 人物 / 设定 / 核心冲突
and returned 5-8 beats. v0.4.0 EXTENDS the schema with:
  * chapters[1..10] populated from the 10-chapter tomato template
  * premise (5-element decomposition: 身份错位 / 状态落差 / 不可逆选择 /
    公开压力 / 情绪补偿)
  * mood_axis (major, minor) — drives body/critique tone

The legacy `beats`/`characters`/`setting`/`central_conflict` fields are
kept for backward compat (body.py / pipeline.py still consume them via
to_prompt_string()). When `chapters` is non-empty the prompt string uses
the new template instead of the legacy `## 幕` section.

Methodology source: tianyayu6/fanqie-hit-short-story methodology.md
(MIT, 2026-06-17), rephrased.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm as default_llm
from fanqie_short_story.prompts import OUTLINE_SYSTEM, OUTLINE_USER_TEMPLATE


GENRES = ("chuanqi", "xianyan", "xuanyi", "tianchong", "naodong")
TONES = ("sweet_with_suspense", "pure_sweet", "tense", "lighthearted")


# ---------------------------------------------------------------------------
# v0.4.0 additions: 10-chapter tomato template
# ---------------------------------------------------------------------------

# Each tuple is (position-title, content-hint). The order is part of the
# methodology; do NOT reorder without re-deriving the body prompt.
CHAPTER_TEMPLATE: list[tuple[str, str]] = [
    ("事故开场",  "羞辱/错认/死亡/婚礼/公开审判/弹幕预警"),
    ("第一次反击", "小动作自证，不大胜"),
    ("关系加压",   "反派把主角逼到更小空间"),
    ("第一反转",   "主角藏着的第一张牌"),
    ("情绪低谷",   "付出代价，虐点具体到人和物"),
    ("布局反杀",   "证据/盟友/身份/账本/录音/弹幕漏洞"),
    ("公开对峙",   "冲突搬到众人面前"),
    ("最大反转",   "真正身份/死亡真相/前世因果/弹幕来源"),
    ("关系清算",   "追悔/断亲/入狱/和离/继承/正名"),
    ("余味收束",   "短场景落地，不讲大道理"),
]

# Default chapter target — ~1200 chars × 10 ≈ 12000 chars body target.
DEFAULT_CHAPTER_TARGET_CHARS = 1200

# Mood axis enum — must match config.defaults.yaml's mood_axis.major.
VALID_MOOD_MAJOR = ("爽", "虐", "甜", "沙雕", "悬疑")


# ---------------------------------------------------------------------------
# ChapterSpec — replaces bare `beats: list[str]` for v0.4.0 callers
# ---------------------------------------------------------------------------


@dataclass
class ChapterSpec:
    """One chapter position in the 番茄 template."""
    index: int                              # 1..10
    title: str                              # "事故开场" etc.
    target_chars: int = DEFAULT_CHAPTER_TARGET_CHARS
    core_event: str = ""                    # 一句话
    emotional_value: str = ""               # "爽"/"虐"/"甜"/...
    hook_at_ending: str = ""                # 一句钩子或未解悬念
    twist_or_turn: Optional[str] = None     # 反转 or "—"

    def __post_init__(self) -> None:
        if not 1 <= self.index <= 10:
            raise ValueError(f"ChapterSpec.index must be 1..10; got {self.index}")


# ---------------------------------------------------------------------------
# 5-element premise decomposition
# ---------------------------------------------------------------------------


# When LLM flakes, fall back to a deterministic seed per umbrella genre.
# Keys match the 番茄 methodology exactly.
_GENRE_PREMISE_SEED: dict[str, dict[str, str]] = {
    "chuanqi": {
        "身份错位": "主角的真实血统/继承权与公开身份相反",
        "状态落差": "从被羞辱/被陷害跌到被所有人看轻",
        "不可逆选择": "签下/撕毁/留下某个具体物件（婚书/遗诏/玉佩）",
        "公开压力": "在众人面前/弹幕上公开真相或公开退婚/断亲",
        "情绪补偿": "主角用具体动作（保下物件/拒绝下跪）替代哭诉",
    },
    "xianyan": {
        "身份错位": "伪装身份进入对方生活/被错认成别人",
        "状态落差": "从被宠爱/被信任跌到被冷落/被怀疑",
        "不可逆选择": "签下协议/录下对话/留下录音笔",
        "公开压力": "在订婚宴/家族会议/朋友圈截图上曝光真相",
        "情绪补偿": "主角拿出具体物件作为反制证据",
    },
    "xuanyi": {
        "身份错位": "死者/受害者身份被隐藏",
        "状态落差": "从被信任到成为嫌疑人",
        "不可逆选择": "进入密室/打开旧档案/接受测谎",
        "公开压力": "在直播弹幕/家族微信群上被指控",
        "情绪补偿": "主角用一本账本/监控录像反证",
    },
    "tianchong": {
        "身份错位": "认错人/真假千金",
        "状态落差": "从被忽视跌到被偏爱",
        "不可逆选择": "签下婚书/拒绝前任复合",
        "公开压力": "在订婚宴/直播弹幕公开偏爱宣言",
        "情绪补偿": "主角用具体礼物（婚书/蛋糕/弹幕截图）兑现情绪",
    },
    "naodong": {
        "身份错位": "系统/穿越/金手指赋予的反差身份",
        "状态落差": "从被规则束缚到可以违规",
        "不可逆选择": "按下系统按钮/写下规则",
        "公开压力": "在弹幕/直播间公开新规则",
        "情绪补偿": "主角用一个外化动作（注销账号/撕掉规则书）替代解释",
    },
}


def _map_genre_to_premise_seed(genre: str) -> dict[str, str]:
    """Deterministic fallback premise for an umbrella genre."""
    return _GENRE_PREMISE_SEED.get(genre, _GENRE_PREMISE_SEED["naodong"])


def _normalize_premise_keys(raw: dict[str, str]) -> dict[str, str]:
    """Force a parsed premise dict into the 5-methodology keys. Any
    missing key gets a placeholder so callers always see all 5."""
    canonical = ("身份错位", "状态落差", "不可逆选择", "公开压力", "情绪补偿")
    out: dict[str, str] = {}
    for k in canonical:
        out[k] = str(raw.get(k, "")).strip() or "（待补）"
    return out


def decompose_premise(
    hook: str,
    *,
    genre: str = "chuanqi",
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> dict[str, str]:
    """Extract the 5-element 前提分解 from a hook via LLM. Falls back to
    genre-seed when the LLM returns empty / non-JSON / no recognizable
    keys. Always returns a dict with exactly the 5 methodology keys."""
    raw_prompt = (
        "根据以下钩子抽取 番茄爆款短篇 5 元素前提分解。"
        "严格 JSON 输出（无解释、无 markdown 包裹），键必须为："
        "身份错位 / 状态落差 / 不可逆选择 / 公开压力 / 情绪补偿。\n\n"
        f"钩子：{hook}\n"
    )

    parsed: dict[str, str] = {}
    if config is not None:
        try:
            text = llm(
                raw_prompt,
                config=config,
                max_tokens=600,
                temperature=0.3,
                system="你只输出 JSON 对象，不要任何解释。",
            )
        except Exception:
            text = ""
    else:
        try:
            text = llm(raw_prompt)
        except Exception:
            text = ""

    # Strip code fences if present.
    if isinstance(text, str):
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for k, v in data.items():
                    parsed[str(k)] = str(v)
        except (ValueError, json.JSONDecodeError, TypeError):
            parsed = {}

    if not parsed:
        return _map_genre_to_premise_seed(genre)
    return _normalize_premise_keys(parsed)


# ---------------------------------------------------------------------------
# Outline dataclass — extends v0.3.4 with chapters/premise/mood_axis
# ---------------------------------------------------------------------------


@dataclass
class Outline:
    """v0.4.0 outline schema. Legacy fields (beats/characters/setting/
    central_conflict) are kept populated so body.py and pipeline.py
    callers keep working unchanged."""
    title_seed: str
    beats: list[str] = field(default_factory=list)
    characters: list[dict[str, str]] = field(default_factory=list)
    setting: str = ""
    central_conflict: str = ""

    # v0.4.0 additions
    chapters: list[ChapterSpec] = field(default_factory=list)
    premise: dict[str, str] = field(default_factory=dict)
    mood_axis: tuple[str, Optional[str]] = ("爽", None)

    def to_prompt_string(self) -> str:
        """Render the outline as markdown for body generation and disk
        output (outline.md). Prefer the chapters/premise layout when
        present; fall back to legacy `## 幕` for v0.3.x callers."""
        if self.chapters:
            chapter_lines = []
            for c in self.chapters:
                twist = f"｜反转：{c.twist_or_turn}" if c.twist_or_turn else ""
                chapter_lines.append(
                    f"{c.index}. {c.title}｜核心事件：{c.core_event}"
                    f"｜目标{c.target_chars}字｜情绪{c.emotional_value}"
                    f"｜章末钩子：{c.hook_at_ending}{twist}"
                )
            chapters_md = "\n".join(chapter_lines)

            premise_lines = "\n".join(
                f"- {k}：{v}" for k, v in self.premise.items()
            ) if self.premise else "（无）"

            chars_md = "\n".join(
                f"- {c['name']}：{c['role']}，{c.get('arc', '')}"
                for c in self.characters
            ) if self.characters else "（无）"

            mood_minor = self.mood_axis[1] if self.mood_axis[1] else "无"
            return (
                f"## 番茄模板（10 章，每章 ~1200 字）\n{chapters_md}\n\n"
                f"## 前提分解（5 元素）\n{premise_lines}\n\n"
                f"## 情绪轴\n主情绪：{self.mood_axis[0]}｜副情绪：{mood_minor}\n\n"
                f"## 人物\n{chars_md}\n\n"
                f"## 设定\n{self.setting or '（无）'}\n\n"
                f"## 核心冲突\n{self.central_conflict or '（无）'}"
            )

        # Legacy fallback.
        beats_md = "\n".join(f"{i + 1}. {b}" for i, b in enumerate(self.beats))
        chars_md = "\n".join(
            f"- {c['name']}：{c['role']}，{c.get('arc', '')}"
            for c in self.characters
        )
        return (
            f"## 幕\n{beats_md}\n\n"
            f"## 人物\n{chars_md}\n\n"
            f"## 设定\n{self.setting}\n\n"
            f"## 核心冲突\n{self.central_conflict}"
        )


# ---------------------------------------------------------------------------
# Legacy section parsers (untouched — v0.3.x compat)
# ---------------------------------------------------------------------------


def _extract_section(md: str, heading: str) -> str:
    pattern = rf"##\s*{heading}\s*\n(.*?)(?=\n##|\Z)"
    m = re.search(pattern, md, re.DOTALL)
    return m.group(1).strip() if m else ""


def _parse_numbered_list(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\d+[.、)]\s*(.+)$", line)
        if m:
            out.append(m.group(1).strip())
    return out


def _parse_character_lines(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        line = line.lstrip("-").strip()
        m = re.match(r"^([^：:，,]+)[：:，,]\s*(.+)$", line)
        if not m:
            continue
        name, rest = m.group(1).strip(), m.group(2).strip()
        parts = re.split(r"[，,]", rest, maxsplit=1)
        role = parts[0].strip()
        arc = parts[1].strip() if len(parts) > 1 else ""
        out.append({"name": name, "role": role, "arc": arc})
    return out


# ---------------------------------------------------------------------------
# v0.4.0 chapter-line parser
# ---------------------------------------------------------------------------


def _parse_chapter_lines(text: str) -> list[ChapterSpec]:
    """Parse chapter lines emitted by the LLM in the form
    `<index>. <title>｜核心事件：...｜目标N字｜情绪X｜章末钩子：...`."""
    out: list[ChapterSpec] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)[.、)\s]\s*(.+)$", line)
        if not m:
            continue
        idx = int(m.group(1))
        rest = m.group(2)
        # Split on the full-width pipe '｜'.
        parts = [p.strip() for p in rest.split("｜")]
        if not parts:
            continue
        title = parts[0]
        # Defaults if the LLM left fields blank.
        core_event = ""
        target_chars = DEFAULT_CHAPTER_TARGET_CHARS
        emotional_value = "爽"
        hook_at_ending = ""
        twist_or_turn: Optional[str] = None
        for part in parts[1:]:
            if part.startswith("核心事件"):
                core_event = part.split("：", 1)[1].strip() if "：" in part else part
            elif part.startswith("目标") and part.endswith("字"):
                digits = re.search(r"\d+", part)
                if digits:
                    target_chars = int(digits.group(0))
            elif part.startswith("情绪"):
                emotional_value = part.split("：", 1)[1].strip() if "：" in part else part
            elif part.startswith("章末钩子") or part.startswith("钩子"):
                hook_at_ending = part.split("：", 1)[1].strip() if "：" in part else part
            elif part.startswith("反转"):
                twist_or_turn = part.split("：", 1)[1].strip() if "：" in part else part
        try:
            spec = ChapterSpec(
                index=idx,
                title=title,
                target_chars=target_chars,
                core_event=core_event,
                emotional_value=emotional_value,
                hook_at_ending=hook_at_ending,
                twist_or_turn=twist_or_turn,
            )
        except ValueError:
            continue
        out.append(spec)
    return out


def _parse_outline_md(md: str) -> Outline:
    """Parse LLM markdown into an Outline. v0.4.0 also populates the
    Outline.chapters and Outline.premise fields when present; falls back
    to empty lists when the LLM didn't emit them."""
    beats_section = _extract_section(md, "幕")
    beats = _parse_numbered_list(beats_section)

    chars_section = _extract_section(md, "人物")
    characters = _parse_character_lines(chars_section)

    setting = _extract_section(md, "设定").strip()
    conflict = _extract_section(md, "核心冲突").strip()

    title_seed = (beats[0][:12].rstrip("。.，,") if beats else "")

    chapters_section = _extract_section(md, "章节")
    chapters = _parse_chapter_lines(chapters_section) if chapters_section else []

    premise_section = _extract_section(md, "前提分解")
    premise: dict[str, str] = {}
    if premise_section:
        for line in premise_section.splitlines():
            line = line.strip()
            if line.startswith("-"):
                kv = line.lstrip("-").strip()
                if "：" in kv:
                    k, v = kv.split("：", 1)
                    premise[k.strip()] = v.strip()

    return Outline(
        title_seed=title_seed or (chapters[0].title if chapters else ""),
        beats=beats,
        characters=characters,
        setting=setting,
        central_conflict=conflict,
        chapters=chapters,
        premise=_normalize_premise_keys(premise) if premise else {},
    )


# ---------------------------------------------------------------------------
# Top-level entry: generate_outline
# ---------------------------------------------------------------------------


def _resolve_mood_major(mood_axis: tuple[str, Optional[str]] | None,
                        config: Config | None) -> tuple[str, Optional[str]]:
    """Resolve `(major, minor)` from arg or config.defaults.yaml."""
    if mood_axis and mood_axis[0] in VALID_MOOD_MAJOR:
        return mood_axis
    if config is not None:
        try:
            cfg_major = config.mood_axis.get("default", {}).get("major", "爽")
            if isinstance(cfg_major, str) and cfg_major in VALID_MOOD_MAJOR:
                return (cfg_major, None)
        except AttributeError:
            pass
    return ("爽", None)


def generate_outline(
    hook: str,
    genre: str,
    target_length: int,
    tone: str,
    *,
    mood_axis: tuple[str, Optional[str]] | None = None,
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> Outline:
    """Generate a 5-8 beat + 10-chapter Outline from a hook + genre + length.

    v0.4.0: ALSO decomposes a 5-element premise from the hook. If `chapters`
    is empty after LLM parse, falls back to populating from CHAPTER_TEMPLATE
    using the legacy `beats` if present (so v0.3.x callers still get a
    usable Outline)."""
    if genre not in GENRES:
        raise ValueError(f"Unknown genre: {genre!r} (expected one of {GENRES})")

    mood = _resolve_mood_major(mood_axis, config)

    # Step 1: premise decomposition (best-effort; always returns dict).
    premise = decompose_premise(hook, genre=genre, llm=llm, config=config)

    # Step 2: chapter generation.
    prompt = OUTLINE_USER_TEMPLATE.format(
        hook=hook, genre=genre, target_length=target_length, tone=tone,
    )
    if config is not None:
        md = llm(
            prompt,
            config=config,
            max_tokens=config.outline.get("default_max_tokens", 2000),
            temperature=config.outline.get("default_temperature", 0.6),
            system=OUTLINE_SYSTEM,
        )
    else:
        md = llm(prompt)

    outline = _parse_outline_md(md)
    outline.premise = premise
    outline.mood_axis = mood

    if not outline.chapters and outline.beats:
        # v0.3.4 LLM output: synthesize chapters from beat titles.
        synthesized: list[ChapterSpec] = []
        for i, beat in enumerate(outline.beats[:10]):
            synthesized.append(ChapterSpec(
                index=i + 1,
                title=CHAPTER_TEMPLATE[i][0] if i < len(CHAPTER_TEMPLATE) else f"段落{i + 1}",
                core_event=beat[:80],
                emotional_value="爽",
                hook_at_ending=outline.beats[i + 1][:50] if i + 1 < len(outline.beats) else "",
            ))
        outline.chapters = synthesized

    return outline
