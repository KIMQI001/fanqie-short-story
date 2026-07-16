"""E2E test against real MiniMax-M2.7. Gated by -m 'not e2e' in CI.

Run manually:
    pytest tests/e2e/test_real_generate.py -v -m e2e
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from fanqie_short_story.config import load_config
from fanqie_short_story.pipeline import generate_story


@pytest.mark.e2e
def test_real_generate_one_chuanqi_story(tmp_path: Path) -> None:
    if not os.environ.get("MINIMAX_API_KEY"):
        pytest.skip("MINIMAX_API_KEY not set; e2e requires a real key")
    if not shutil.which("cover_gen"):
        pytest.skip("cover_gen not on PATH; e2e needs cover_gen installed")
    cfg = load_config(Path("config/defaults.yaml"))
    out = generate_story(
        hook="重生后我成了侯府嫡女，发现前世夫君是害我的凶手",
        genre="chuanqi",
        target_length=8000,
        output_dir=tmp_path,
        config=cfg,
    )
    assert (out / "outline.md").exists()
    assert (out / "body.txt").exists()
    assert (out / "titles.txt").exists()
    assert (out / "synopsis.md").exists()
    body_text = (out / "body.txt").read_text(encoding="utf-8")
    # ±50% of 8000 — wider than pipeline's ±20% because real LLM length
    # control is fuzzy.
    assert 4000 <= len(body_text) <= 12000
    assert "未完待续" not in body_text
    assert "林晚" in body_text or "侯府" in body_text  # hooked into the prompt
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["critique_strategy"] == "heuristic_then_llm"
    assert data["heuristic_attempts"] >= 1
    assert data["llm_critic_attempts"] >= 0
