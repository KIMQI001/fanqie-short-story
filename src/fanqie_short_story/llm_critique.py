"""LLM-based critic: 5-aspect narrative review of generated bodies.

Augments the heuristic critique with a deeper LLM-driven review. Runs ONLY
when the heuristic passes (cost control). Failed critic → full body regenerate
with critic's prose notes injected into the next body prompt (wrapped as
`[notes]` since body.py expects `critique_feedback: list[str]`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from fanqie_short_story.body import Body, _strip_json_fences
from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm
from fanqie_short_story.prompts import LLM_CRITIQUE_SYSTEM, LLM_CRITIQUE_USER_TEMPLATE


_VERDICT_RE = re.compile(r"verdict\s*[:：]\s*(pass|fail)\b", re.IGNORECASE)

_ASPECT_TERMS = ("钩子", "情节", "人物", "节奏", "语言")


@dataclass
class LLMCritiqueReport:
    passed: bool
    notes: str                              # full prose; always populated (sentinel on empty response)
    mentioned_aspects: list[str] = field(default_factory=list)
    raw_response: str = ""


def _parse_verdict(text: str) -> tuple[bool, str]:
    """Find VERDICT line bottom-up. Returns (passed, full_prose).

    No VERDICT line → (False, full_prose) defensive.
    Full-width colon tolerated.
    Empty response → (False, "(empty critic response)") per spec §5.3.
    """
    cleaned = _strip_json_fences(text).strip()
    if not cleaned:
        return False, "(empty critic response)"
    for line in reversed(cleaned.splitlines()):
        m = _VERDICT_RE.search(line)
        if m:
            return m.group(1).lower() == "pass", cleaned
    return False, cleaned


def _extract_mentioned_aspects(text: str) -> list[str]:
    return [term for term in _ASPECT_TERMS if term in text]


def llm_critique(
    body: Body,
    hook: str,
    genre: str,
    target_length: int,
    *,
    llm: Callable[..., str] = call_llm,
    config: Config,
) -> LLMCritiqueReport:
    prompt = LLM_CRITIQUE_USER_TEMPLATE.format(
        hook=hook, genre=genre, target_length=target_length, body=body.text,
    )
    raw = llm(
        prompt,
        config=config,
        max_tokens=config.critique.get("llm_max_tokens", 2000),
        temperature=config.critique.get("llm_temperature", 0.3),
        system=LLM_CRITIQUE_SYSTEM,
    )
    passed, prose = _parse_verdict(raw)
    return LLMCritiqueReport(
        passed=passed,
        notes=prose,
        mentioned_aspects=[] if passed else _extract_mentioned_aspects(prose),
        raw_response=raw,
    )