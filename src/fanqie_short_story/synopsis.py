"""Three-segment 导语 (lead) replacing v0.3.4's one-paragraph 简介.

Adapted from tianyayu6/fanqie-hit-short-story methodology.md "三段导语公式"
(rephrased; MIT license):

  钩子段 (hook)        : 违背常识的开场  (≤60字)
  冲突段 (conflict)    : 核心压迫 + 退路 + 损失  (≤60字)
  人设段 (protagonist) : 主角的主动锋利反应  (≤60字)

generate_lead() returns a LeadParagraph dataclass with all three segments
plus a `\n\n`-joined `combined` field for downstream consumers.

generate_synopsis() is kept as a backward-compat shim — it returns the
`combined` string for v0.3.4 callers (CLI, batch, etc.). Tests still call
the shim with `llm=fake` and expect a single string back.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from fanqie_short_story.body import Body
from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm as default_llm


# v0.4.0 system prompt — three-segment 导语 in strict JSON.
_LEAD_SYSTEM_V040 = (
    "你是番茄爆款导语编辑。给一段正文写三段导语，严格 JSON 输出：\n"
    '{"hook":"...", "conflict":"...", "protagonist_voice":"..."}\n\n'
    "钩子段（第一段）: 违背常识的开场（≤60字）\n"
    "冲突段（第二段）: 核心压迫 + 退路 + 损失（≤60字）\n"
    "人设段（第三段）: 主角的主动锋利反应（≤60字）\n"
)


@dataclass
class LeadParagraph:
    hook: str            # 第一段：违背常识的开场
    conflict: str        # 第二段：核心压迫 + 退路 + 损失
    protagonist_voice: str  # 第三段：主动锋利的反应
    combined: str        # 三段拼接（"\n\n"）


def _call_lead_llm(
    body: Body, hook: str,
    *, llm: Callable[..., str], config: Config | None,
) -> str:
    """Call the LLM for the three-segment lead. Returns raw text (may be JSON
    wrapped in fences or preceded by prose)."""
    user = f"核心梗:{hook}\n正文:{body.text[:4000]}"
    if config is not None:
        return llm(
            user, config=config, max_tokens=600, temperature=0.6,
            system=_LEAD_SYSTEM_V040,
        )
    return llm(user)


def _parse_lead_json(raw: str) -> dict[str, str] | None:
    """Extract {hook, conflict, protagonist_voice} from raw LLM output.

    Handles prose-wrapped JSON, fenced JSON, and inline JSON. Returns None
    if no JSON object can be located or parsed.
    """
    s = raw.strip()
    m = re.search(r"\{[\s\S]*?\}", s)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return {
        "hook": str(obj.get("hook", "")),
        "conflict": str(obj.get("conflict", "")),
        "protagonist_voice": str(obj.get("protagonist_voice", "")),
    }


def generate_lead(
    body: Body,
    hook: str,
    genre: str,
    *,
    n_chars: int = 120,
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> LeadParagraph:
    """Three-segment lead generation. Used by cover back-blurb + manifest.

    Falls back to a deterministic construction if LLM flaked or JSON
    parsing failed: `combined` becomes the body's first paragraph
    (truncated to n_chars).
    """
    raw = _call_lead_llm(body, hook, llm=llm, config=config)
    parsed = _parse_lead_json(raw)
    if parsed is not None and any(parsed.values()):
        combined = "\n\n".join([
            parsed["hook"], parsed["conflict"], parsed["protagonist_voice"],
        ]).strip()
        return LeadParagraph(
            hook=parsed["hook"],
            conflict=parsed["conflict"],
            protagonist_voice=parsed["protagonist_voice"],
            combined=combined,
        )

    # Fallback: deterministic construction from body's first paragraph.
    first_para = body.text.split("\n\n", 1)[0].strip()[:n_chars]
    return LeadParagraph(
        hook=hook[:60],
        conflict="",
        protagonist_voice="",
        combined=first_para,
    )


# Backward-compat shim: older callers (CLI, batch) used generate_synopsis
# returning a single string. Preserve that contract.
def generate_synopsis(
    body: Body,
    hook: str,
    genre: str,
    *,
    n: int = 120,
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> str:
    """v0.3.4 compat shim. Returns the combined lead as a single string.

    v0.4.0 callers should prefer generate_lead() which returns the full
    LeadParagraph dataclass (hook/conflict/protagonist_voice/combined).
    """
    lead = generate_lead(body, hook, genre, n_chars=n, llm=llm, config=config)
    return lead.combined
