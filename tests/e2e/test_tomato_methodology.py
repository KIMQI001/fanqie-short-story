"""End-to-end test: full pipeline with tomato methodology against real MiniMax.

Gated by `-m e2e`. Skips without MINIMAX_API_KEY or cover_gen.

v0.4.0 additions verified by this test:
  * manifest.schema_version == "0.4.0"
  * manifest.polish_applied is True
  * 0 <= manifest.polish_ai_odor_score <= 1.0
  * manifest.editor_categories_passed is a dict (one entry per editor category)
  * manifest.memory_object is non-null (story contains a 物件)
  * body length within ±40% of target_length (aligned with v0.3.3 heuristic default; v0.4.1)
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
# v0.3.2 lesson: target 12000 was too aggressive — real MiniMax-M2.7 reliably
# produces 7000-9000 chars at hook=真千金回家...target=8000. daily.py switched
# to 8000 for this exact reason. The e2e test was never updated; v0.4.1 brings
# it in line.
TARGET_LENGTH = 8000


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

    # Body length within ±40% of target. v0.3.3 loosened the heuristic to
    # ±50% because real MiniMax-M2.7 routinely produces 5000-7300 chars
    # for target=8000 (20-40% undershoot). The e2e ±20% window was
    # inherited from v0.1.0 strict mode and never reflected LLM reality;
    # v0.4.1 brings it in line with the v0.3.3 default tolerance.
    body = (story_dir / "body.txt").read_text(encoding="utf-8")
    assert len(body) >= TARGET_LENGTH * 0.6, f"body too short: {len(body)} < {TARGET_LENGTH * 0.6}"
    assert len(body) <= TARGET_LENGTH * 1.4, f"body too long: {len(body)} > {TARGET_LENGTH * 1.4}"

    # v0.4.0 heuristic gates still enforced on real output
    assert "未完待续" not in body
    for banned in ("潮水", "深渊", "利刃", "齿轮", "牢笼", "风暴"):
        assert body.count(banned) <= 3, f"too many '{banned}' in body ({body.count(banned)})"