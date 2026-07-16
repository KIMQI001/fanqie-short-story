"""Hermetic CLI tests for v0.3.0 daily + daemon subcommands (no real LLM/launchctl)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from fanqie_short_story.cli import main


def _patch_load_config(monkeypatch) -> MagicMock:
    """Patch `load_config` on the cli module so `main()` can construct without
    a real `config/defaults.yaml` or env vars. Returns the fake config.
    """
    fake_cfg = MagicMock()
    monkeypatch.setattr("fanqie_short_story.cli.load_config", lambda path: fake_cfg)
    return fake_cfg


def test_daily_run_once_invokes_run_daily(tmp_path: Path, monkeypatch) -> None:
    """`fanqie-story daily run-once` calls daily.run_daily and exits 0 on success.

    `main()` loads Config eagerly at top-level callback, so we must patch
    `load_config` to return a MagicMock — otherwise the test fails on a missing
    `config/defaults.yaml` inside `runner.isolated_filesystem()` BEFORE the
    `daily run-once` subcommand ever runs.
    """
    _patch_load_config(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem():
        scorer = Path("scorer")
        runs = scorer / "output" / "runs" / "2026-W29"
        runs.mkdir(parents=True)
        (runs / "scores.csv").write_text(
            "rank,book_id,title,author,genre,overall,rationale\n"
            "1,id1,t1,a1,xuanhuan,7.0,r\n",
            encoding="utf-8",
        )
        with patch("fanqie_short_story.cli.run_daily") as mock_run:
            mock_run.return_value = type(
                "R", (), {
                    "date": "2026-07-16", "source_csv": Path("x.csv"),
                    "generated": [], "failures": [], "api_calls": 0,
                }
            )()
            result = runner.invoke(
                main,
                ["--config", "config/defaults.yaml", "daily", "run-once",
                 "--scorer-root", str(scorer), "--top-n", "5"],
            )
        assert result.exit_code == 0, result.output + result.stderr
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["top_n"] == 5
        assert kwargs["scorer_root"] == scorer


def test_daemon_install_invokes_install(monkeypatch) -> None:
    """`fanqie-story daemon install` calls daemon.install.

    `main()` loads Config eagerly at the top-level callback, so we must patch
    `load_config` to return a MagicMock — otherwise `MINIMAX_API_KEY` is unset
    and `load_config` raises ConfigError BEFORE `daemon_install` is invoked.
    """
    _patch_load_config(monkeypatch)
    runner = CliRunner()
    with patch("fanqie_short_story.cli.install") as mock_install:
        result = runner.invoke(
            main,
            ["daemon", "install", "--time", "07:30"],
        )
    assert result.exit_code == 0, result.output + result.stderr
    mock_install.assert_called_once()
    assert mock_install.call_args.kwargs["schedule_time"] == "07:30"


def test_daemon_status_invokes_status(monkeypatch) -> None:
    """`fanqie-story daemon status` calls daemon.status and prints report.

    `main()` loads Config eagerly at the top-level callback, so we must patch
    `load_config` to return a MagicMock — otherwise `MINIMAX_API_KEY` is unset
    and `load_config` raises ConfigError BEFORE `daemon status` is reached.
    Same uniform mocking contract as the other two tests in this file.
    """
    _patch_load_config(monkeypatch)
    runner = CliRunner()
    fake_report = type(
        "R", (), {
            "installed": True, "loaded": True, "schedule_time": "06:00",
            "env_key_present": True,
            "plist_path": Path.home() / "Library/LaunchAgents/com.fanqie-short-story.daily.plist",
            "last_run_log": Path("/tmp/logs/daily-2026-07-16.log"),
        }
    )()
    with patch("fanqie_short_story.cli.status", return_value=fake_report):
        result = runner.invoke(main, ["daemon", "status"])
    assert result.exit_code == 0, result.output + result.stderr
    # Per spec §3.2, the status command prints these explicit field labels:
    for label in ("installed:", "loaded:", "plist_path:", "schedule_time:",
                  "env_key:", "last_run_log:"):
        assert label in result.output, f"missing field {label!r} in status output"
