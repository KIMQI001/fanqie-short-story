"""End-to-end test: full pipeline with tomato methodology against real MiniMax.

Gated by `-m e2e`. Skips without MINIMAX_API_KEY or cover_gen.

v0.4.0 additions verified by this test:
  * manifest.schema_version == "0.4.0"
  * manifest.polish_applied is True
  * 0 <= manifest.polish_ai_odor_score <= 1.0
  * manifest.editor_categories_passed is a dict (one entry per editor category)
  * manifest.memory_object is non-null (story contains a 物件)
  * body length within ±20% of target_length (the LLM-tuned v0.4.0 tolerance)
  * no forbidden opener words (未完待续)
  * low occurrence of banned 抽象 metaphors (潮水/深渊/利刃/齿轮/牢笼/风暴)
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from fanqie_short_story.config import load_config
from fanqie_short_story.pipeline import generate_story


pytestmark = pytest.mark.e2e


HOOK = "真千金回家那天，我发现自己手里攥着一张快递单。"
GENRE = "xianyan"
TARGET_LENGTH = 12000


@pytest.fixture
def cfg(tmp_path: Path):
    if not os.environ.get("MINIMAX_API_KEY"):
        pytest.skip("MINIMAX_API_KEY not set; e2e requires a real key")
    if not shutil.which("cover_gen"):
        pytest.skip("cover_gen not on PATH; e2e needs cover_gen installed")
    return load_config(Path("config/defaults.yaml"))


def test_full_pipeline_with_tomato_methodology(cfg, tmp_path):
    story_dir = generate_story(
        hook=HOOK, genre=GENRE, target_length=TARGET_LENGTH,
        config=cfg, output_dir=tmp_path, slug="fanqie-hit-e2e",
    )
    manifest = json.loads((story_dir / "manifest.json").read_text(encoding="utf-8"))

    # v0.4.0 schema + polish wiring
    assert manifest.get("schema_version") == "0.4.0"
    assert manifest.get("polish_applied") is True
    assert 0 <= manifest.get("polish_ai_odor_score", 0.0) <= 1.0
    assert isinstance(manifest.get("editor_categories_passed"), dict)
    assert manifest.get("memory_object") is not None

    # Body length within ±20% of target
    body = (story_dir / "body.txt").read_text(encoding="utf-8")
    assert len(body) >= TARGET_LENGTH * 0.8, f"body too short: {len(body)} < {TARGET_LENGTH * 0.8}"
    assert len(body) <= TARGET_LENGTH * 1.2, f"body too long: {len(body)} > {TARGET_LENGTH * 1.2}"

    # v0.4.0 heuristic gates still enforced on real output
    assert "未完待续" not in body
    for banned in ("潮水", "深渊", "利刃", "齿轮", "牢笼", "风暴"):
        assert body.count(banned) <= 3, f"too many '{banned}' in body ({body.count(banned)})"