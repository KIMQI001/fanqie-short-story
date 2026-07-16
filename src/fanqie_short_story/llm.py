"""LLM transport — httpx + Anthropic-compatible Messages API, pointed at MiniMax.

Mirrors fanqie-topic-scorer's score.py pattern: skip thinking blocks, strip
JSON fences, fall through to plain text. No `response_format` kwarg (Anthropic
Messages API has none).
"""
from __future__ import annotations

from typing import Any

import httpx

from fanqie_short_story.config import Config


class LLMError(Exception):
    """Raised on 4xx (no retry) — caller decides what to do for 5xx."""


def _strip_thinking_blocks(response: dict) -> str:
    """MiniMax returns [ThinkingBlock, TextBlock]; only text blocks are real output."""
    parts: list[str] = []
    for block in response.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def call_llm(
    prompt: str,
    *,
    config: Config,
    max_tokens: int,
    temperature: float,
    system: str | None = None,
) -> str:
    """Call MiniMax Messages API. Returns the model's text content.

    Raises LLMError on 4xx (no retry). httpx.HTTPError propagates on 5xx
    (caller decides whether to retry).
    """
    body: dict[str, Any] = {
        "model": config.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    url = f"{config.api_base.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    resp = httpx.post(url, json=body, headers=headers, timeout=300.0)
    if 400 <= resp.status_code < 500:
        raise LLMError(f"LLM {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    return _strip_thinking_blocks(resp.json())
