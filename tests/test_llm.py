"""Unit tests for llm.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fanqie_short_story.llm import LLMError, _strip_thinking_blocks, call_llm


def test_strip_thinking_blocks_drops_thinking_keeps_text() -> None:
    """MiniMax returns [ThinkingBlock, TextBlock]; only TextBlock is real output."""
    fake_response = {
        "content": [
            {"type": "thinking", "thinking": "internal reasoning..."},
            {"type": "text", "text": "the actual answer"},
        ]
    }
    assert _strip_thinking_blocks(fake_response) == "the actual answer"


def test_strip_thinking_blocks_concatenates_multiple_text() -> None:
    fake_response = {
        "content": [
            {"type": "thinking", "thinking": "..."},
            {"type": "text", "text": "part 1 "},
            {"type": "text", "text": "part 2"},
        ]
    }
    assert _strip_thinking_blocks(fake_response) == "part 1 part 2"


def test_strip_thinking_blocks_handles_empty_content() -> None:
    assert _strip_thinking_blocks({"content": []}) == ""


def test_call_llm_posts_to_anthropic_messages_endpoint(fake_config) -> None:
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "content": [{"type": "text", "text": "hi"}]
        }
        return resp

    with patch("fanqie_short_story.llm.httpx.post", side_effect=fake_post):
        text = call_llm(
            "hello", config=fake_config, max_tokens=100, temperature=0.5,
        )
    assert text == "hi"
    assert captured["url"] == "https://api.minimaxi.com/anthropic/v1/messages"
    assert captured["json"]["model"] == "MiniMax-M2.7"
    assert captured["json"]["max_tokens"] == 100
    assert captured["json"]["temperature"] == 0.5
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert "anthropic-version" in captured["headers"]


def test_call_llm_includes_system_when_provided(fake_config) -> None:
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"content": [{"type": "text", "text": "ok"}]}
        return resp

    with patch("fanqie_short_story.llm.httpx.post", side_effect=fake_post):
        call_llm("p", config=fake_config, max_tokens=10, temperature=0.5,
                 system="you are helpful")
    assert captured["json"]["system"] == "you are helpful"


def test_call_llm_raises_on_4xx(fake_config) -> None:
    resp = MagicMock(status_code=401, text="invalid api key")
    with patch("fanqie_short_story.llm.httpx.post", return_value=resp):
        with pytest.raises(LLMError, match="401"):
            call_llm(
                "x", config=fake_config, max_tokens=100, temperature=0.5,
            )


def test_call_llm_strips_trailing_slash_in_api_base(fake_config) -> None:
    cfg = type(fake_config)(
        **{**fake_config.__dict__, "api_base": "https://api.minimaxi.com/anthropic/"}
    )
    captured: dict = {}

    def fake_post(url, **kw):
        captured["url"] = url
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"content": [{"type": "text", "text": "ok"}]}
        return resp

    with patch("fanqie_short_story.llm.httpx.post", side_effect=fake_post):
        call_llm("p", config=cfg, max_tokens=10, temperature=0.5)
    assert captured["url"] == "https://api.minimaxi.com/anthropic/v1/messages"
