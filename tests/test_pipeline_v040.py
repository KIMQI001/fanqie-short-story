"""Tests for v0.4.0 pipeline extensions.

v0.4.0 ADDS to pipeline.py:
  * outline backtrack on structural-severity editor-critic failure
    (capped by config.critique.editor_max_structural_failures, default 1)
  * de-AI-flavor polish.run() applied AFTER body passes critic
  * memory_object detection (first strong-object match in body)
  * new manifest fields: polish_applied, polish_intensity, polish_ai_odor_score,
    polish_rules_applied, outline_backtrack_count, editor_categories_passed,
    memory_object, mood_axis, schema_version

The v0.2.0 llm_critique path is REPLACED by llm_editor_critique in v0.4.0.
Existing pipeline tests in test_pipeline.py use editor_critique mocks.

Methodology source: tianyayu6/fanqie-hit-short-story methodology.md
(MIT, 2026-06-17), 番茄 爆款 short-story pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pytest

from fanqie_short_story.body import Body
from fanqie_short_story.config import Config
from fanqie_short_story.outline import Outline
from fanqie_short_story.pipeline import generate_story


# ---------------------------------------------------------------------------
# Helpers — fake_config with v0.4.0 polish/mood_axis fields populated
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_config_v040() -> Config:
    """fake_config extended with v0.4.0 polish/mood_axis/length_tier blocks."""
    return Config(
        model="MiniMax-M2.7",
        api_base="https://api.minimaxi.com/anthropic",
        api_key="sk-test",
        max_retries=3,
        critique={
            "length_tolerance": 0.50,
            "hook_window_chars": 200,
            "ending_window_chars": 500,
            "max_pov_switches": 8,
            "llm_enabled": True,
            "llm_max_tokens": 2000,
            "llm_temperature": 0.3,
            "llm_max_calls_per_story": 3,
            "editor_max_structural_failures": 1,
        },
        body={"default_temperature": 0.7, "default_max_tokens": 20000},
        outline={"default_temperature": 0.6, "default_max_tokens": 2000},
        title={"candidate_count": 5},
        synopsis={"target_length_chars": 120},
        cover={"default_backend": "auto", "image_size": [600, 800]},
        genre_mapping={},
        daily={},
        polish={"enabled": True, "default_intensity": 1,
                "full_llm": False, "auto_bump_on_backtrack": True},
        mood_axis={"default": {"major": "爽", "minor": None},
                   "major": ["爽", "虐", "甜", "沙雕", "悬疑"]},
        length_tier={"default": "ultra_short",
                     "ultra_short": {"min_chars": 8000,
                                     "default_chars": 12000,
                                     "max_chars": 24900}},
    )


def _outline_with_chapters() -> Outline:
    """Outline with all v0.4.0 fields populated (chapters + premise + mood_axis)."""
    from fanqie_short_story.outline import ChapterSpec, CHAPTER_TEMPLATE
    chapters = [
        ChapterSpec(index=i + 1, title=t, core_event=f"事件{i + 1}",
                    emotional_value="爽", hook_at_ending=f"钩子{i + 1}")
        for i, (t, _hint) in enumerate(CHAPTER_TEMPLATE)
    ]
    return Outline(
        title_seed="测试",
        beats=["事件1", "事件2"],
        characters=[{"name": "林晚", "role": "主角", "arc": "反击"}],
        setting="侯府",
        central_conflict="身份错位",
        chapters=chapters,
        premise={"身份错位": "原是嫡女却被弃养",
                 "状态落差": "从侯府跌为婢女",
                 "不可逆选择": "在婚书上签字",
                 "公开压力": "弹幕公告断亲",
                 "情绪补偿": "保下婚书做证据"},
        mood_axis=("爽", None),
    )


def _outline_legacy() -> Outline:
    """Pre-v0.4.0 Outline (no chapters/premise/mood_axis)."""
    return Outline(
        title_seed="林晚",
        beats=["起：重生", "承：搜集", "转：反击", "合：破局", "收：归隐"],
        characters=[{"name": "林晚", "role": "主角", "arc": ""}],
        setting="侯府",
        central_conflict="林晚必须先发制人",
    )


def _good_body_text() -> str:
    """A 1500-char body that passes heuristic gates AND contains a memory
    object (婚书) so memory_object detection succeeds."""
    return (
        "第一章 重生\n\n"
        "弹幕警告：「林晚活不过三章。」我撕掉婚书，把行李箱推到门口。"
        "我把外卖单压在病历下，带着转账记录走了。"
        "刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 25
        + "真相大白，归隐山林，从此再无风波。"
    )


def _editor_critic_pass(*_a, **_kw):
    """Editor critic that always passes all 5 categories."""
    from fanqie_short_story.llm_critique import EditorReport, CategoryVerdict
    return EditorReport(categories=[
        CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
        CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="节奏", passed=True, notes="", severity="surface"),
    ])


def _editor_critic_structural_fail(*_a, **_kw):
    """Editor critic that fails 开篇 (structural) on every call."""
    from fanqie_short_story.llm_critique import EditorReport, CategoryVerdict
    return EditorReport(categories=[
        CategoryVerdict(name="开篇", passed=False, notes="开篇 100 字无冲突",
                        severity="structural"),
        CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
        CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="节奏", passed=True, notes="", severity="surface"),
    ])


def _editor_critic_structural_then_pass(call_log: list):
    """Editor critic: structural fail on 1st call, pass on 2nd."""
    from fanqie_short_story.llm_critique import EditorReport, CategoryVerdict
    def _f(*_a, **_kw):
        call_log.append(1)
        if len(call_log) == 1:
            return EditorReport(categories=[
                CategoryVerdict(name="开篇", passed=False, notes="开篇 100 字无冲突",
                                severity="structural"),
                CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
                CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
                CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
                CategoryVerdict(name="节奏", passed=True, notes="", severity="surface"),
            ])
        return _editor_critic_pass()
    return _f


def _editor_critic_surface_only(*_a, **_kw):
    """Editor critic that fails 节奏 (surface only) — should NOT backtrack."""
    from fanqie_short_story.llm_critique import EditorReport, CategoryVerdict
    return EditorReport(categories=[
        CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
        CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
        CategoryVerdict(name="节奏", passed=False, notes="节奏过慢",
                        severity="surface"),
    ])


# ---------------------------------------------------------------------------
# Outline backtrack on structural failure
# ---------------------------------------------------------------------------


def test_pipeline_backtracks_to_outline_on_structural_failure(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Editor critic returns structural_failure=True on first call; pipeline
    regenerates outline + body; second body passes; outline_backtrack_count=1."""
    outline_calls: list[int] = []
    body_calls: list[int] = []
    call_log: list[int] = []

    def fake_outline(*a, **kw):
        outline_calls.append(1)
        return _outline_legacy()

    def fake_body(*a, **kw):
        body_calls.append(1)
        return Body.from_text(_good_body_text())

    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_structural_then_pass(call_log)), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="重生侯府", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(outline_calls) == 2, f"expected 2 outline calls; got {len(outline_calls)}"
    assert len(body_calls) == 2, f"expected 2 body calls; got {len(body_calls)}"
    assert len(call_log) == 2
    assert data["outline_backtrack_count"] == 1


def test_pipeline_caps_backtracks_at_one(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Editor critic ALWAYS returns structural_failure=True; pipeline
    backs off after 1 outline regen and accepts the body with
    outline_backtrack_count=1."""
    outline_calls: list[int] = []

    def fake_outline(*a, **kw):
        outline_calls.append(1)
        return _outline_legacy()

    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(_good_body_text())), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_structural_fail), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(outline_calls) == 2
    assert data["outline_backtrack_count"] == 1
    # Cap reached with structural failure still present → accept-with-cap flag set.
    assert data["accepted_after_critic_cap"] is True
    assert data["critique_strategy"] == "heuristic_then_editor"


def test_pipeline_skips_backtrack_on_surface_failure(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Editor critic returns surface-only failure (节奏); pipeline retries
    body without regenerating outline. outline_backtrack_count=0."""
    outline_calls: list[int] = []
    body_calls: list[int] = []

    def fake_outline(*a, **kw):
        outline_calls.append(1)
        return _outline_legacy()

    def fake_body(*a, **kw):
        body_calls.append(1)
        return Body.from_text(_good_body_text())

    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_surface_only), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    assert len(outline_calls) == 1
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["outline_backtrack_count"] == 0


# ---------------------------------------------------------------------------
# Polish wiring
# ---------------------------------------------------------------------------


def test_pipeline_runs_polish_after_body_passes(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Body passes critic → polish.run() applies intensity=1 → body.txt
    is the polished output. 抽象比喻 cluster gets stripped."""
    body_text = _good_body_text() + "潮水般的忧伤涌上心头。"
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_legacy()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(body_text)), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_pass), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=2000,
            output_dir=tmp_path, config=fake_config_v040,
        )
    final_body = (out / "body.txt").read_text(encoding="utf-8")
    assert "潮水般" not in final_body, \
        f"polish should strip 潮水般; got: {final_body[-200:]!r}"
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["polish_applied"] is True
    assert data["polish_intensity"] == 1


def test_pipeline_skips_polish_when_disabled_in_config(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """config.polish.enabled=False → body.txt contains original text
    verbatim; manifest.polish_applied=False."""
    body_text = _good_body_text() + "潮水般的忧伤涌上心头。"
    fake_config_v040.polish["enabled"] = False
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_legacy()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(body_text)), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_pass), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=2000,
            output_dir=tmp_path, config=fake_config_v040,
        )
    final_body = (out / "body.txt").read_text(encoding="utf-8")
    assert "潮水般" in final_body
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["polish_applied"] is False
    assert data["polish_intensity"] == 0


def test_pipeline_records_polish_ai_odor_score_in_manifest(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Manifest has polish_ai_odor_score (float 0..1)."""
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_legacy()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(_good_body_text())), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_pass), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data["polish_ai_odor_score"], (int, float))
    assert 0.0 <= data["polish_ai_odor_score"] <= 1.0


def test_pipeline_auto_bumps_polish_intensity_on_backtrack(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """When outline backtrack fires, polish intensity auto-bumps 1→2."""
    call_log: list[int] = []
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_legacy()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(_good_body_text())), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_structural_then_pass(call_log)), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["outline_backtrack_count"] == 1
    assert data["polish_intensity"] == 2, \
        f"expected intensity 2 after backtrack; got {data['polish_intensity']}"


# ---------------------------------------------------------------------------
# New manifest fields
# ---------------------------------------------------------------------------


def test_pipeline_emits_mood_axis_and_memory_object_in_manifest(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Outline has mood_axis=("爽", None) + body contains 婚书 →
    manifest.mood_axis and manifest.memory_object populated correctly."""
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_with_chapters()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(_good_body_text())), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_pass), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["mood_axis"] is not None
    assert data["mood_axis"][0] == "爽"
    assert data["memory_object"] == "婚书", \
        f"expected memory_object='婚书'; got {data['memory_object']!r}"


def test_pipeline_emits_editor_categories_passed_in_manifest(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Manifest has editor_categories_passed mapping each category→bool."""
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_legacy()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(_good_body_text())), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_pass), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    cats = data["editor_categories_passed"]
    assert isinstance(cats, dict)
    assert set(cats.keys()) == {"开篇", "梗与题材", "情绪兑现", "人物", "节奏"}
    assert all(cats.values()), f"all_passed → all True; got {cats}"


def test_pipeline_emits_schema_version_in_manifest(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Manifest has schema_version='0.4.0'."""
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_legacy()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(_good_body_text())), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_pass), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "0.4.0"


def test_pipeline_emits_outline_backtrack_count_zero_on_success(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """Happy path → manifest.outline_backtrack_count=0."""
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_legacy()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(_good_body_text())), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_pass), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["outline_backtrack_count"] == 0


# ---------------------------------------------------------------------------
# Polish NEVER raises — pipeline must not crash on empty/None body
# ---------------------------------------------------------------------------


def test_pipeline_handles_polish_on_clean_body_without_change(
    tmp_path: Path, fake_config_v040: Config,
) -> None:
    """A body with no AI-odor markers is left untouched; polish_applied=True
    but rules_applied=[]."""
    with patch("fanqie_short_story.pipeline.generate_outline",
               return_value=_outline_legacy()), \
         patch("fanqie_short_story.pipeline.generate_body",
               return_value=Body.from_text(_good_body_text())), \
         patch("fanqie_short_story.pipeline.llm_editor_critique",
               side_effect=_editor_critic_pass), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1500,
            output_dir=tmp_path, config=fake_config_v040,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["polish_applied"] is True
    assert isinstance(data["polish_rules_applied"], list)