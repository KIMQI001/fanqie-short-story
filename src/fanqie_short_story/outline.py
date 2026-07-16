"""Outline generator: hook + genre + length + tone → Outline.

The LLM is required to emit markdown with sections: 幕 / 人物 / 设定 / 核心冲突.
The parser is lenient — missing sections become empty.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm as default_llm
from fanqie_short_story.prompts import OUTLINE_SYSTEM, OUTLINE_USER_TEMPLATE


GENRES = ("chuanqi", "xianyan", "xuanyi", "tianchong", "naodong")
TONES = ("sweet_with_suspense", "pure_sweet", "tense", "lighthearted")


@dataclass
class Outline:
    title_seed: str
    beats: list[str]
    characters: list[dict[str, str]]
    setting: str
    central_conflict: str

    def to_prompt_string(self) -> str:
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


def _parse_outline_md(md: str) -> Outline:
    beats_section = _extract_section(md, "幕")
    beats = _parse_numbered_list(beats_section)

    chars_section = _extract_section(md, "人物")
    characters = _parse_character_lines(chars_section)

    setting = _extract_section(md, "设定").strip()
    conflict = _extract_section(md, "核心冲突").strip()

    title_seed = (beats[0][:12].rstrip("。.，,") if beats else "")

    return Outline(
        title_seed=title_seed,
        beats=beats,
        characters=characters,
        setting=setting,
        central_conflict=conflict,
    )


def generate_outline(
    hook: str,
    genre: str,
    target_length: int,
    tone: str,
    *,
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> Outline:
    """Generate a 5-8 beat Outline from a hook + genre + length + tone."""
    if genre not in GENRES:
        raise ValueError(f"Unknown genre: {genre!r} (expected one of {GENRES})")
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
    return _parse_outline_md(md)
