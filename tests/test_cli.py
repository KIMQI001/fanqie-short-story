"""Unit tests for cli.py."""
from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from fanqie_short_story.cli import main


def test_cli_generate_happy_path(tmp_path: Path) -> None:
    fake_dir = tmp_path / "story"
    with patch("fanqie_short_story.cli.generate_story", return_value=fake_dir):
        runner = CliRunner()
        result = runner.invoke(main, [
            "generate",
            "--hook", "重生侯府",
            "--genre", "chuanqi",
            "--length", "12000",
            "--output-dir", str(tmp_path),
        ])
    assert result.exit_code == 0, result.output
    assert str(fake_dir) in result.output


def test_cli_generate_rejects_unknown_genre(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, [
        "generate", "--hook", "h", "--genre", "bogus", "--length", "1000",
        "--output-dir", str(tmp_path),
    ])
    assert result.exit_code != 0
    assert "Invalid value" in result.output or "genre" in result.output.lower()


def test_cli_batch_reads_csv_and_calls_generate(tmp_path: Path) -> None:
    csv_path = tmp_path / "scores.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "id", "title", "author", "genre", "blurb",
                    "in_read", "score", "c", "h", "e", "p", "d", "rationale"])
        w.writerow(["1", "x", "末：土匪", "作者A", "kehuan-moshi", "", "100",
                    "8.2", "8", "8", "8", "8", "9", "土匪在末世抢资源，差异化极强"])
        w.writerow(["2", "y", "凡骨", "作者B", "xuanhuan-xiuzhen", "", "200",
                    "8.0", "9", "8", "9", "8", "8", "凡骨逆袭，扩展性强"])
    with patch("fanqie_short_story.cli.generate_story", return_value=tmp_path) as gs:
        runner = CliRunner()
        result = runner.invoke(main, [
            "batch", "--from-report", str(csv_path),
            "--genre", "xianyan",  # fallback for unmapped
            "--length", "8000",
            "--limit", "2",
            "--output-dir", str(tmp_path),
        ])
    assert result.exit_code == 0, result.output
    assert gs.call_count == 2


def test_cli_generate_surfaces_generation_failed(tmp_path: Path) -> None:
    from fanqie_short_story.pipeline import GenerationFailed
    err = GenerationFailed("critique loop exhausted", output_dir=tmp_path)
    with patch("fanqie_short_story.cli.generate_story", side_effect=err):
        runner = CliRunner()
        result = runner.invoke(main, [
            "generate",
            "--hook", "h",
            "--genre", "chuanqi",
            "--length", "1000",
            "--output-dir", str(tmp_path),
        ])
    assert result.exit_code != 0
    combined = result.output + (result.stderr or "")
    assert "generation failed" in combined or "critique" in combined
