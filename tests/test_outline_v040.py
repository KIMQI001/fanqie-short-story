"""Tests for v0.4.0 outline.py extensions.

Adds ChapterSpec + 10-chapter template + 5-element premise decomposition +
mood_axis parameterization on top of the v0.3.4 Outline dataclass. The
existing `beats`/`characters`/`setting`/`central_conflict` fields stay
(read-only compatibility for body.py which consumes `to_prompt_string()`).

Methodology source: tianyayu6/fanqie-hit-short-story methodology.md,
10-chapter template (事故→反击→加压→反转→低谷→反杀→对峙→最大反转→
清算→收束) and 5-element premise decomposition (身份错位+状态落差+
不可逆选择+公开压力+情绪补偿).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fanqie_short_story.outline import (
    CHAPTER_TEMPLATE,
    ChapterSpec,
    Outline,
    _map_genre_to_premise_seed,
    decompose_premise,
    generate_outline,
)
from fanqie_short_story.config import Config


# ---------------------------------------------------------------------------
# 10-chapter template catalogue
# ---------------------------------------------------------------------------


def test_chapter_template_has_ten_positions() -> None:
    """The tomato methodology hard-defines 10 chapter positions (1-10,
    with positions 9-10 being optional). Length MUST be 10."""
    assert isinstance(CHAPTER_TEMPLATE, list)
    assert len(CHAPTER_TEMPLATE) == 10, f"expected 10 chapter positions; got {len(CHAPTER_TEMPLATE)}"
    for i, (title, hint) in enumerate(CHAPTER_TEMPLATE, start=1):
        assert isinstance(title, str) and title, f"position {i} has empty title"
        assert isinstance(hint, str) and hint, f"position {i} has empty hint"


def test_chapter_template_order_matches_methodology() -> None:
    """The 10 positions must follow the published order. Pinning this so
    a future careless edit doesn't reorder (e.g. swap 反杀 with 对峙)."""
    titles = [t for t, _ in CHAPTER_TEMPLATE]
    expected_substrings = [
        "事故开场", "反击", "加压", "反转", "低谷",
        "反杀", "对峙", "最大反转", "清算", "收束",
    ]
    for i, expected in enumerate(expected_substrings):
        assert expected in titles[i], (
            f"position {i + 1} expected substring {expected!r}; got {titles[i]!r}"
        )


# ---------------------------------------------------------------------------
# ChapterSpec dataclass
# ---------------------------------------------------------------------------


def test_chapter_spec_defaults_target_chars_to_1200() -> None:
    """Default ~1200 chars × 10 chapters ≈ 12000 chars body target.
    Tolerance is ±10% per chapter; the prompt-level instruction is what
    actually constrains LLM output."""
    cs = ChapterSpec(index=1, title="事故开场", core_event="主角被退婚。",
                     emotional_value="虐", hook_at_ending="弹幕预警。")
    assert cs.target_chars == 1200


def test_chapter_spec_rejects_index_out_of_range() -> None:
    """Indexes MUST be 1..10 (validated loudly; downstream body.py and
    cover_gen rely on consistent indexing)."""
    with pytest.raises((ValueError, AssertionError)):
        ChapterSpec(index=0, title="x", core_event="x",
                    emotional_value="爽", hook_at_ending="x")
    with pytest.raises((ValueError, AssertionError)):
        ChapterSpec(index=11, title="x", core_event="x",
                    emotional_value="爽", hook_at_ending="x")


# ---------------------------------------------------------------------------
# 5-element premise decomposition
# ---------------------------------------------------------------------------


def test_decompose_premise_returns_five_element_dict() -> None:
    """decompose_premise(hook) must return a dict with exactly the 5
    methodology keys, all non-empty strings."""
    out = decompose_premise(
        "重生后我被侯府退婚，弹幕说我活不过三章",
        llm=lambda *_a, **_kw: _fake_premise_md(),
    )
    for key in ("身份错位", "状态落差", "不可逆选择",
                "公开压力", "情绪补偿"):
        assert key in out, f"missing premise key: {key}"
        assert isinstance(out[key], str)
        assert out[key].strip(), f"empty value for premise key {key}"


def test_decompose_premise_falls_back_when_llm_flaked() -> None:
    """If the LLM flaked (returned empty / non-JSON), decompose_premise
    MUST still return a 5-element dict by inferring from genre."""
    out = decompose_premise(
        "公告离婚当日我把户口迁走了",
        llm=lambda *_a, **_kw: "",
        genre="chuanqi",
    )
    assert set(out.keys()) == {"身份错位", "状态落差", "不可逆选择",
                                "公开压力", "情绪补偿"}
    for v in out.values():
        assert isinstance(v, str) and v.strip(), f"empty fallback value: {v!r}"


def test_map_genre_to_premise_seed_is_deterministic() -> None:
    """Genre → 5-element seed must be stable (no randomness). Used when
    LLM flakes; the fallback MUST give callers consistent keys."""
    for genre in ("chuanqi", "xianyan", "xuanyi", "tianchong", "naodong"):
        seed = _map_genre_to_premise_seed(genre)
        assert isinstance(seed, dict)
        assert set(seed.keys()) == {"身份错位", "状态落差", "不可逆选择",
                                     "公开压力", "情绪补偿"}


# ---------------------------------------------------------------------------
# Outline.to_prompt_string — new chapters layout
# ---------------------------------------------------------------------------


def _sample_outline_with_chapters() -> Outline:
    chapters = [
        ChapterSpec(index=i + 1, title=t, core_event=f"事件{i + 1}",
                    emotional_value=("爽" if i % 2 == 0 else "虐"),
                    hook_at_ending=f"钩子{i + 1}")
        for i, (t, _hint) in enumerate(CHAPTER_TEMPLATE)
    ]
    return Outline(
        title_seed="测试",
        beats=[],
        characters=[{"name": "林晚", "role": "主角", "arc": "反击"}],
        setting="侯府",
        central_conflict="身份错位",
        chapters=chapters,
        premise={"身份错位": "主角原是嫡女却被弃养",
                 "状态落差": "从侯府嫡女跌为婢女",
                 "不可逆选择": "在婚书上签字",
                 "公开压力": "弹幕公告侯府与主角断亲",
                 "情绪补偿": "主角保下婚书作为证据"},
        mood_axis=("爽", None),
    )


def test_outline_to_prompt_string_includes_all_ten_chapter_positions() -> None:
    out = _sample_outline_with_chapters()
    prompt = out.to_prompt_string()
    for title, _hint in CHAPTER_TEMPLATE:
        assert title in prompt, f"chapter position {title!r} missing from prompt"


def test_outline_to_prompt_string_includes_mood_axis() -> None:
    out = _sample_outline_with_chapters()
    prompt = out.to_prompt_string()
    assert "爽" in prompt, "mood major should be rendered"
    # minor=None should also surface (operator sees '无' or '-' marker).
    assert "无" in prompt or "—" in prompt or "-" in prompt, \
        "no-mood-minor marker should be present"


def test_outline_to_prompt_string_includes_five_element_premise() -> None:
    out = _sample_outline_with_chapters()
    prompt = out.to_prompt_string()
    for key in ("身份错位", "状态落差", "不可逆选择", "公开压力", "情绪补偿"):
        assert key in prompt, f"premise key {key!r} missing from prompt"


def test_outline_to_prompt_string_falls_back_to_beats_when_no_chapters() -> None:
    """Pre-v0.4.0 callers still get the legacy beats format when a
    caller constructs an Outline without chapters."""
    out = Outline(
        title_seed="legacy",
        beats=["事件1", "事件2"],
        characters=[],
        setting="",
        central_conflict="",
    )
    prompt = out.to_prompt_string()
    assert "事件1" in prompt
    assert "## 幕" in prompt, "legacy '## 幕' section must survive"


# ---------------------------------------------------------------------------
# generate_outline — extends signature with mood_axis + accepts llm kwarg
# ---------------------------------------------------------------------------


def test_generate_outline_returns_outline_with_chapters() -> None:
    """generate_outline now returns Outline.chapters populated by the
    mock LLM output. Verifies the happy path end-to-end without network."""
    md = _fake_chapter_md()
    captured: dict = {}

    def fake_llm(prompt, **_kw):
        captured["prompt"] = prompt
        return md

    config = Config(
        model="MiniMax-M2.7", api_base="https://api.minimaxi.com/anthropic",
        api_key="sk-test", max_retries=3,
        critique={}, body={}, outline={}, title={},
        synopsis={}, cover={}, genre_mapping={},
    )
    out = generate_outline(
        hook="被退婚后我当场签字", genre="chuanqi",
        target_length=12000, tone="sweet_with_suspense",
        mood_axis=("爽", None),
        llm=fake_llm, config=config,
    )
    assert isinstance(out, Outline)
    assert out.chapters, "chapters must be populated when LLM returns markdown"
    assert len(out.chapters) == 10, f"expected 10 chapters; got {len(out.chapters)}"
    # Mood axis is threaded through to Outline.
    assert out.mood_axis == ("爽", None)


def test_generate_outline_mood_axis_defaults_when_omitted() -> None:
    """When mood_axis kwarg is omitted, the function falls back to the
    config-default (爽 / null) rather than raising."""
    def fake_llm(prompt, **_kw):
        return _fake_chapter_md()
    config = Config(
        model="MiniMax-M2.7", api_base="https://api.minimaxi.com/anthropic",
        api_key="sk-test", max_retries=3,
        critique={}, body={}, outline={}, title={},
        synopsis={}, cover={}, genre_mapping={},
    )
    out = generate_outline(
        hook="x", genre="chuanqi", target_length=12000,
        tone="sweet_with_suspense",
        llm=fake_llm, config=config,
    )
    # Default per config.defaults.yaml: ('爽', None).
    assert out.mood_axis and out.mood_axis[0] == "爽"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_premise_md() -> str:
    return (
        "## 前提分解\n"
        "身份错位：原是嫡女却被弃养\n"
        "状态落差：从侯府跌为婢女\n"
        "不可逆选择：在婚书上签字\n"
        "公开压力：弹幕公告断亲\n"
        "情绪补偿：保下婚书做证据\n"
    )


def _fake_chapter_md() -> str:
    lines = ["## 章节\n"]
    for i, (title, hint) in enumerate(CHAPTER_TEMPLATE, start=1):
        lines.append(f"{i}. {title}｜{hint}｜目标{i * 1200}字｜情绪爽｜结尾：钩子{i}")
    lines.append("\n## 人物\n- 林晚：主角，反击")
    lines.append("\n## 设定\n侯府")
    lines.append("\n## 核心冲突\n身份错位")
    return "\n".join(lines)
