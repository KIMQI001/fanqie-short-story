"""Unit tests for llm_critique.py."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fanqie_short_story.body import Body
from fanqie_short_story.llm_critique import LLMCritiqueReport, llm_critique


def _body() -> Body:
    return Body.from_text(
        "刀光剑影之间，林晚撞见了沈墨，她必须先发制人。真相大白，归隐山林。"
    )


def test_llm_critique_passes_when_verdict_pass(fake_config) -> None:
    fake_config.critique["llm_enabled"] = True
    fake_llm = MagicMock(return_value="整体不错。\nVERDICT: PASS")
    report = llm_critique(
        _body(), hook="h", genre="chuanqi", target_length=1000,
        llm=fake_llm, config=fake_config,
    )
    assert report.passed is True
    assert "整体不错" in report.notes
    assert report.mentioned_aspects == []


def test_llm_critique_fails_when_verdict_fail(fake_config) -> None:
    fake_config.critique["llm_enabled"] = True
    fake_llm = MagicMock(return_value="节奏拖沓，情节有漏洞。\nVERDICT: FAIL")
    report = llm_critique(
        _body(), hook="h", genre="chuanqi", target_length=1000,
        llm=fake_llm, config=fake_config,
    )
    assert report.passed is False
    assert "节奏拖沓" in report.notes
    assert "情节有漏洞" in report.notes


def test_llm_critique_fails_when_no_verdict_line(fake_config) -> None:
    fake_config.critique["llm_enabled"] = True
    fake_llm = MagicMock(return_value="整体评价：可以更好。")
    report = llm_critique(
        _body(), hook="h", genre="chuanqi", target_length=1000,
        llm=fake_llm, config=fake_config,
    )
    assert report.passed is False
    assert "可以更好" in report.notes


def test_llm_critique_handles_json_fences(fake_config) -> None:
    fake_config.critique["llm_enabled"] = True
    fake_llm = MagicMock(return_value="```\n整体不错。\nVERDICT: PASS\n```")
    report = llm_critique(
        _body(), hook="h", genre="chuanqi", target_length=1000,
        llm=fake_llm, config=fake_config,
    )
    assert report.passed is True


def test_llm_critique_uses_correct_temperature_and_max_tokens(fake_config) -> None:
    fake_config.critique["llm_enabled"] = True
    fake_config.critique["llm_max_tokens"] = 1500
    fake_config.critique["llm_temperature"] = 0.5
    fake_llm = MagicMock(return_value="VERDICT: PASS")
    llm_critique(
        _body(), hook="h", genre="chuanqi", target_length=1000,
        llm=fake_llm, config=fake_config,
    )
    kwargs = fake_llm.call_args.kwargs
    assert kwargs["max_tokens"] == 1500
    assert kwargs["temperature"] == 0.5
    assert kwargs["system"] is not None  # system prompt passed
    assert fake_llm.call_args.args[0]  # prompt positional


def test_llm_critique_extracts_mentioned_aspects(fake_config) -> None:
    fake_config.critique["llm_enabled"] = True
    fake_llm = MagicMock(return_value=(
        "钩子不够强。情节闭环尚可。节奏拖沓。语言OK。\nVERDICT: FAIL"
    ))
    report = llm_critique(
        _body(), hook="h", genre="chuanqi", target_length=1000,
        llm=fake_llm, config=fake_config,
    )
    assert "钩子" in report.mentioned_aspects
    assert "节奏" in report.mentioned_aspects


def test_llm_critique_handles_full_width_colon_verdict(fake_config) -> None:
    fake_config.critique["llm_enabled"] = True
    fake_llm = MagicMock(return_value="情节有漏洞。\nVERDICT：FAIL")
    report = llm_critique(
        _body(), hook="h", genre="chuanqi", target_length=1000,
        llm=fake_llm, config=fake_config,
    )
    assert report.passed is False


def test_llm_critique_fails_when_empty_response(fake_config) -> None:
    """Empty LLM response → spec §5.3: FAIL with sentinel notes."""
    fake_config.critique["llm_enabled"] = True
    fake_llm = MagicMock(return_value="")
    report = llm_critique(
        _body(), hook="h", genre="chuanqi", target_length=1000,
        llm=fake_llm, config=fake_config,
    )
    assert report.passed is False
    assert report.notes == "(empty critic response)"