"""Synopsis generator: 50-200 字 intro from body + hook."""
from __future__ import annotations

import re
from typing import Callable

from fanqie_short_story.body import Body
from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm as default_llm
from fanqie_short_story.prompts import SYNOPSIS_SYSTEM, SYNOPSIS_USER_TEMPLATE


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:[a-z]*\n)?", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def generate_synopsis(
    body: Body,
    hook: str,
    genre: str,
    *,
    n: int = 120,
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> str:
    body_head = body.text[:400]
    prompt = SYNOPSIS_USER_TEMPLATE.format(
        hook=hook, genre=genre, n=n, body_head=body_head,
    )
    if config is not None:
        raw = llm(
            prompt, config=config, max_tokens=400, temperature=0.6,
            system=SYNOPSIS_SYSTEM,
        )
    else:
        raw = llm(prompt)
    return _strip_fences(raw)
