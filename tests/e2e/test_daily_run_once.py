"""End-to-end: real fanqie-topic-scorer scores.csv + real MiniMax → 5 stories.

Gated by `-m e2e` (skipped by default per existing test layout in
tests/e2e/test_real_generate.py).

Run: `python -m pytest tests/e2e/test_daily_run_once.py -m e2e -v`
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fanqie_short_story.cli import main
from click.testing import CliRunner


SCORER_ROOT = Path.home() / "CascadeProjects" / "projects" / "fanqie-topic-scorer"


@pytest.mark.e2e
def test_daily_run_once_against_real_minimax(tmp_path: Path) -> None:
    """Run daily run-once against real scorer + real MiniMax. Asserts manifest + 5 stories."""
    if not (SCORER_ROOT / "output" / "runs").exists():
        pytest.skip(f"{SCORER_ROOT}/output/runs missing — no live scores.csv to consume")
    if not (os.environ.get("MINIMAX_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("MINIMAX_API_KEY / ANTHROPIC_API_KEY not set — no real key to score with")

    # Use an isolated output dir to avoid clobbering real output/daily
    output_root = tmp_path / "daily"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "daily", "run-once",
            "--scorer-root", str(SCORER_ROOT),
            "--output-root", str(output_root),
            "--top-n", "5",
            # --no-notify is REQUIRED in tests; without it the CLI calls
            # osascript and pops a system notification dialog (spec §5
            # #notification is best-effort but still fires).
            "--no-notify",
        ],
    )
    if result.exit_code != 0:
        # Surface output for debugging
        pytest.fail(f"daily run-once failed: exit {result.exit_code}\n"
                    f"STDOUT: {result.output}\nSTDERR: {result.stderr}")

    # Locate the manifest by scanning the day's subdir (output_root/<YYYY-MM-DD>/).
    # We MUST NOT compute `date.today()` here — on long e2e runs this would race
    # the CLI across midnight in local time and look for the manifest on the
    # wrong day. The CLI uses `datetime.now().date()`; we mirror that by
    # finding the most recently modified day subdir.
    day_subdirs = sorted(
        (p for p in output_root.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
    )
    assert day_subdirs, (
        f"no day subdir under {output_root} — daily run-once didn't write any output"
    )
    manifest_path = day_subdirs[-1] / "daily_manifest.json"
    assert manifest_path.exists(), f"missing manifest at {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["totals"]["succeeded"] == 5
    assert len(manifest["generated"]) == 5
    # At least 1 cover.jpg across the 5 story dirs
    cover_count = sum(
        1 for entry in manifest["generated"]
        if Path(entry["story_dir"]).joinpath("cover.jpg").exists()
    )
    assert cover_count >= 1, "no cover.jpg found in any story_dir"
    # All 5 manifests have a valid critique_strategy
    for entry in manifest["generated"]:
        assert entry["critique_strategy"] in ("heuristic_then_llm", "heuristic_only"), \
            f"unexpected critique_strategy: {entry['critique_strategy']}"