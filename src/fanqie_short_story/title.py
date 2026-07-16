"""Title candidates generator: 3-5 short hooky titles from body + hook."""
from __future__ import annotations

from typing import Callable

from fanqie_short_story.body import Body
from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm as default_llm
from fanqie_short_story.prompts import TITLE_SYSTEM, TITLE_USER_TEMPLATE


def generate_titles(
    body: Body,
    hook: str,
    genre: str,
    *,
    n: int = 5,
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> list[str]:
    body_head = body.text[:400]
    prompt = TITLE_USER_TEMPLATE.format(
        hook=hook, genre=genre, n=n, body_head=body_head,
    )
    if config is not None:
        raw = llm(
            prompt, config=config, max_tokens=400, temperature=0.8,
            system=TITLE_SYSTEM,
        )
    else:
        raw = llm(prompt)
    titles = [t.strip() for t in raw.splitlines() if t.strip()]
    # Drop duplicates while preserving order, cap at n.
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= n:
            break
    return out
