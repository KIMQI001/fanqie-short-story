"""Body generator: Outline + hook + length → Body (plain text, 1-3万字)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm as default_llm
from fanqie_short_story.outline import Outline
from fanqie_short_story.prompts import BODY_SYSTEM, BODY_USER_TEMPLATE


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
    if config is not None:
        raw = llm(
            prompt,
            config=config,
            max_tokens=config.body.get("default_max_tokens", 20000),
            temperature=config.body.get("default_temperature", 0.7),
            system=BODY_SYSTEM,
        )
    else:
        raw = llm(prompt)
    return Body.from_text(_strip_json_fences(raw))
