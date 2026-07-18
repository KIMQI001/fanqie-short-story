"""Unit tests for pipeline.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from fanqie_short_story.body import Body
from fanqie_short_story.outline import Outline
from fanqie_short_story.pipeline import GenerationFailed, generate_story


def _outline() -> Outline:
    return Outline(
        title_seed="林晚",
        beats=["起：重生", "承：搜集", "转：反击", "合：破局", "收：归隐"],
        characters=[{"name": "林晚", "role": "主角", "arc": ""}],
        setting="侯府",
        central_conflict="林晚必须先发制人",
    )


def _llm_critique_pass():
    """Return an llm_editor_critique side_effect that always PASSes (no network).

    v0.4.0: pipeline now uses llm_editor_critique (5-category editor review)
    instead of v0.2.0's llm_critique. This helper builds a pass-everything
    EditorReport."""
    from fanqie_short_story.llm_critique import EditorReport, CategoryVerdict

    def _fake(*a, **kw):
        return EditorReport(categories=[
            CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
            CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="节奏", passed=True, notes="", severity="surface"),
        ])
    return _fake


def test_generate_story_writes_all_outputs(tmp_path: Path, fake_config) -> None:
    def fake_outline(*args, **kw):
        return _outline()
    def fake_body(*args, **kw):
        # Sized to ~1410 chars; target 1400 → window 1120-1680, passes length.
        text = ("第一章 重生\n\n刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 50
                + "真相大白，归隐山林。")
        return Body.from_text(text)
    def fake_titles(*args, **kw):
        return ["重生侯府", "侯门嫡女", "血洗侯门"]
    def fake_synopsis(*args, **kw):
        return "林晚重生回侯府，发现前世夫君是凶手。"
    def fake_cover(*args, **kw):
        # Mimic real cover_gen: write cover.jpg into <output_dir>/<slug>/.
        slug = kw.get("slug") or args[0]
        output_dir = kw.get("output_dir") or args[3]
        (Path(output_dir) / slug).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / slug / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        return "minimax"
    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.llm_editor_critique", side_effect=_llm_critique_pass()), \
         patch("fanqie_short_story.pipeline.generate_titles", side_effect=fake_titles), \
         patch("fanqie_short_story.pipeline.generate_synopsis", side_effect=fake_synopsis), \
         patch("fanqie_short_story.pipeline.generate_cover", side_effect=fake_cover):
        out = generate_story(
            hook="重生侯府", genre="chuanqi", target_length=1400,
            output_dir=tmp_path, config=fake_config,
        )
    assert (out / "outline.md").exists()
    assert (out / "body.txt").exists()
    assert (out / "titles.txt").exists()
    assert (out / "synopsis.md").exists()
    assert (out / "cover.jpg").exists()
    assert (out / "manifest.json").exists()


def test_generate_story_retries_on_critique_fail(tmp_path: Path, fake_config) -> None:
    """First body is bad (weak hook, unresolved ending, off-length).
    Second body is good (passes all gates). Verify retry happens."""
    call_count = {"body": 0}
    def fake_outline(*args, **kw):
        return _outline()
    def fake_body(*args, **kw):
        call_count["body"] += 1
        if call_count["body"] == 1:
            # Weak setup, no hook signals, unresolved ending, off-length.
            text = ("在一个阳光明媚的早晨，我醒来了。"
                    + ("情节。" * 800) + "未完待续")
            return Body.from_text(text)
        # Sized to ~1629 chars; target 2000 → window 1600-2400, passes length.
        # Has 撞见 + 必须 hooks, ends with 真相大白...归隐.
        text = ("刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 70
                + "真相大白，归隐山林，从此再无风波。")
        return Body.from_text(text)
    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.llm_editor_critique", side_effect=_llm_critique_pass()), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=2000,
            output_dir=tmp_path, config=fake_config,
        )
    assert call_count["body"] >= 2  # retried at least once
    assert (out / "body.txt").exists()


def test_generate_story_raises_after_max_retries(tmp_path: Path, fake_config) -> None:
    def fake_outline(*args, **kw):
        return _outline()
    def always_bad(*args, **kw):
        # Always fails hook (no signals), ending (未完待续), length (14 chars).
        return Body.from_text("未完待续" + ("x" * 10))
    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=always_bad), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        with pytest.raises(GenerationFailed) as exc_info:
            generate_story(
                hook="h", genre="chuanqi", target_length=1000,
                output_dir=tmp_path, config=fake_config,
            )
    assert (exc_info.value.output_dir / "_failed").exists()


def test_generate_story_continues_when_cover_fails(tmp_path: Path, fake_config) -> None:
    """Cover failure must NOT block the rest of the pipeline."""
    def fake_outline(*args, **kw):
        return _outline()
    def fake_body(*args, **kw):
        text = ("第一章 重生\n\n刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 50
                + "真相大白，归隐山林。")
        return Body.from_text(text)
    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.llm_editor_critique", side_effect=_llm_critique_pass()), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover",
               side_effect=RuntimeError("comfyui down")):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1400,
            output_dir=tmp_path, config=fake_config,
        )
    assert (out / "body.txt").exists()
    assert (out / "manifest.json").exists()
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["cover_backend"] is None


# === v0.2.0 additions ===

def test_pipeline_runs_llm_critic_after_heuristic_pass(tmp_path, fake_config) -> None:
    """Heuristic PASS + LLM critic PASS → done in 1 attempt."""
    fake_config.critique["llm_enabled"] = True
    fake_config.critique["llm_max_calls_per_story"] = 3

    def fake_outline(*a, **kw): return _outline()
    def fake_body(*a, **kw):
        text = ("第一章 重生\n\n刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 50
                + "真相大白，归隐山林。")
        return Body.from_text(text)
    def fake_heuristic(*a, **kw):
        from fanqie_short_story.critique import CritiqueReport
        return CritiqueReport(passed=True, notes=[], failed_gates=[])
    def fake_llm_critique(*a, **kw):
        from fanqie_short_story.llm_critique import EditorReport, CategoryVerdict
        return EditorReport(categories=[
            CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
            CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="节奏", passed=True, notes="", severity="surface"),
        ])

    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.heuristic_critique", side_effect=fake_heuristic) as mock_h, \
         patch("fanqie_short_story.pipeline.llm_editor_critique", side_effect=fake_llm_critique) as mock_llm, \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1400,
            output_dir=tmp_path, config=fake_config,
        )
    assert mock_h.call_count == 1
    assert mock_llm.call_count == 1
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["critique_strategy"] == "heuristic_then_editor"
    assert data["llm_critic_attempts"] == 1
    assert data["accepted_after_critic_cap"] is False


def test_pipeline_retries_when_llm_critic_fails(tmp_path, fake_config) -> None:
    """Heuristic PASS + LLM critic FAIL → retry with [critic notes]."""
    fake_config.critique["llm_enabled"] = True
    fake_config.critique["llm_max_calls_per_story"] = 3

    def fake_outline(*a, **kw): return _outline()
    def fake_body(*a, **kw):
        text = ("第一章 重生\n\n刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 50
                + "真相大白，归隐山林。")
        return Body.from_text(text)
    def fake_heuristic(*a, **kw):
        from fanqie_short_story.critique import CritiqueReport
        return CritiqueReport(passed=True, notes=[], failed_gates=[])
    call_count = {"llm": 0}
    def fake_llm_critique(*a, **kw):
        from fanqie_short_story.llm_critique import EditorReport, CategoryVerdict
        call_count["llm"] += 1
        if call_count["llm"] == 1:
            # Surface-only failure (节奏) → pipeline retries body, no outline backtrack
            return EditorReport(categories=[
                CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
                CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
                CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
                CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
                CategoryVerdict(name="节奏", passed=False, notes="节奏拖沓", severity="surface"),
            ])
        return EditorReport(categories=[
            CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
            CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="节奏", passed=True, notes="", severity="surface"),
        ])

    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.heuristic_critique", side_effect=fake_heuristic), \
         patch("fanqie_short_story.pipeline.llm_editor_critique", side_effect=fake_llm_critique), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1400,
            output_dir=tmp_path, config=fake_config,
        )
    assert call_count["llm"] == 2  # retried once
    assert (out / "body.txt").exists()


def test_pipeline_skips_llm_critic_when_heuristic_fails(tmp_path, fake_config) -> None:
    """Heuristic always fails → LLM critic never runs."""
    fake_config.critique["llm_enabled"] = True

    def fake_outline(*a, **kw): return _outline()
    def always_bad_body(*a, **kw):
        return Body.from_text("未完待续" + ("x" * 10))
    def fail_heuristic(*a, **kw):
        from fanqie_short_story.critique import CritiqueReport
        return CritiqueReport(passed=False, notes=["钩子太弱"], failed_gates=["hook"])

    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=always_bad_body), \
         patch("fanqie_short_story.pipeline.heuristic_critique", side_effect=fail_heuristic), \
         patch("fanqie_short_story.pipeline.llm_editor_critique") as mock_llm, \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        with pytest.raises(GenerationFailed):
            generate_story(
                hook="h", genre="chuanqi", target_length=1000,
                output_dir=tmp_path, config=fake_config,
            )
    assert mock_llm.call_count == 0


def test_pipeline_caps_llm_critic_calls(tmp_path, fake_config) -> None:
    """Heuristic always PASS + LLM critic always FAIL → cap accepts body."""
    fake_config.critique["llm_enabled"] = True
    fake_config.critique["llm_max_calls_per_story"] = 2

    def fake_outline(*a, **kw): return _outline()
    def fake_body(*a, **kw):
        text = ("第一章 重生\n\n刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 50
                + "真相大白，归隐山林。")
        return Body.from_text(text)
    def fake_heuristic(*a, **kw):
        from fanqie_short_story.critique import CritiqueReport
        return CritiqueReport(passed=True, notes=[], failed_gates=[])
    def always_fail_llm_critique(*a, **kw):
        # v0.4.0: pipeline uses EditorReport (5 categories, surface vs
        # structural severity). Surface-only failure so the cap is hit
        # WITHOUT triggering outline backtrack.
        from fanqie_short_story.llm_critique import EditorReport, CategoryVerdict
        return EditorReport(categories=[
            CategoryVerdict(name="开篇", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="梗与题材", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="情绪兑现", passed=True, notes="", severity="surface"),
            CategoryVerdict(name="人物", passed=True, notes="", severity="structural"),
            CategoryVerdict(name="节奏", passed=False, notes="节奏拖沓", severity="surface"),
        ])

    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.heuristic_critique", side_effect=fake_heuristic), \
         patch("fanqie_short_story.pipeline.llm_editor_critique", side_effect=always_fail_llm_critique), \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1400,
            output_dir=tmp_path, config=fake_config,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["accepted_after_critic_cap"] is True
    assert data["llm_critic_attempts"] == 2


def test_pipeline_records_critique_strategy_in_manifest(tmp_path, fake_config) -> None:
    """critique_strategy follows config.critique.llm_enabled."""
    fake_config.critique["llm_enabled"] = False  # kill switch

    def fake_outline(*a, **kw): return _outline()
    def fake_body(*a, **kw):
        text = ("第一章 重生\n\n刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 50
                + "真相大白，归隐山林。")
        return Body.from_text(text)
    def fake_heuristic(*a, **kw):
        from fanqie_short_story.critique import CritiqueReport
        return CritiqueReport(passed=True, notes=[], failed_gates=[])

    with patch("fanqie_short_story.pipeline.generate_outline", side_effect=fake_outline), \
         patch("fanqie_short_story.pipeline.generate_body", side_effect=fake_body), \
         patch("fanqie_short_story.pipeline.heuristic_critique", side_effect=fake_heuristic), \
         patch("fanqie_short_story.pipeline.llm_editor_critique") as mock_llm, \
         patch("fanqie_short_story.pipeline.generate_titles", return_value=["t"]), \
         patch("fanqie_short_story.pipeline.generate_synopsis", return_value="s"), \
         patch("fanqie_short_story.pipeline.generate_cover", return_value="minimax"):
        out = generate_story(
            hook="h", genre="chuanqi", target_length=1400,
            output_dir=tmp_path, config=fake_config,
        )
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["critique_strategy"] == "heuristic_only"
    assert mock_llm.call_count == 0
