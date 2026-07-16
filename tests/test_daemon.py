"""Tests for fanqie_short_story.daemon — macOS launchd integration."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

from fanqie_short_story.daemon import (
    LABEL, PLIST_PATH, render_plist,
)


def test_render_plist_includes_schedule_time() -> None:
    """Plist XML contains <string>06:00</string> in StartCalendarInterval Hour."""
    xml = render_plist(
        schedule_time="06:00",
        log_dir=Path("/tmp/logs"),
        scorer_root=Path("/tmp/scorer"),
        fanqie_story_root=Path("/tmp/story"),
    )
    # Plist has separate <integer>6</integer><integer>0</integer> for Hour/Minute
    assert "<integer>6</integer>" in xml
    assert "<integer>0</integer>" in xml
    assert "StartCalendarInterval" in xml


def test_render_plist_program_arguments_include_daily_run_once() -> None:
    """Plist XML references the daily-run-once console script."""
    xml = render_plist(
        schedule_time="06:00",
        log_dir=Path("/tmp/logs"),
        scorer_root=Path("/tmp/scorer"),
        fanqie_story_root=Path("/tmp/story"),
    )
    # The plist's ProgramArguments should invoke fanqie-story-run (the console
    # script registered in Task 1; the script itself lives in daemon.py's
    # run_with_notification — see Chunk 4).
    assert "fanqie-story-run" in xml or "ProgramArguments" in xml
    # It should also include both scorer_root and fanqie_story_root in env
    assert "FANQIE_SCORER_ROOT" in xml
    assert "FANQIE_STORY_ROOT" in xml


def test_render_plist_label_matches_constant() -> None:
    """Plist Label is com.troah.fanqie-short-story.daily."""
    xml = render_plist(
        schedule_time="06:00",
        log_dir=Path("/tmp/logs"),
        scorer_root=Path("/tmp/scorer"),
        fanqie_story_root=Path("/tmp/story"),
    )
    assert LABEL in xml
    assert "com.troah.fanqie-short-story.daily" in xml


def test_render_plist_includes_throttle_interval() -> None:
    """Plist sets ThrottleInterval=3600 so launchd retries at most hourly (spec §5)."""
    xml = render_plist(
        schedule_time="06:00",
        log_dir=Path("/tmp/logs"),
        scorer_root=Path("/tmp/scorer"),
        fanqie_story_root=Path("/tmp/story"),
    )
    assert "<key>ThrottleInterval</key>" in xml
    assert "<integer>3600</integer>" in xml


from fanqie_short_story.daemon import (
    install, parse_env_file, write_env_file, write_plist,
)


def test_parse_env_file_handles_quotes_and_comments(tmp_path: Path) -> None:
    """Tolerates blanks, comments, and quoted values."""
    env_file = tmp_path / "env"
    env_file.write_text(
        "# comment\n"
        "\n"
        "MINIMAX_API_KEY='sk-abc'\n"
        "OTHER=\"value with spaces\"\n"
        "BARE=bare-value\n",
        encoding="utf-8",
    )
    result = parse_env_file(env_file)
    assert result == {
        "MINIMAX_API_KEY": "sk-abc",
        "OTHER": "value with spaces",
        "BARE": "bare-value",
    }


def test_write_env_file_chmods_0600(tmp_path: Path) -> None:
    """Atomic write (tmp + rename) with chmod 0o600."""
    env_file = tmp_path / "sub" / "env"
    write_env_file(env_file, {"MINIMAX_API_KEY": "sk-xyz"})
    assert env_file.exists()
    mode = env_file.stat().st_mode & 0o777
    assert mode == 0o600
    assert parse_env_file(env_file) == {"MINIMAX_API_KEY": "sk-xyz"}


def test_install_writes_plist_to_launch_agents(tmp_path: Path, monkeypatch) -> None:
    """install() writes the plist file at the expected path and calls
    `launchctl load -w <plist>` (subprocess mocked so no real launchctl runs)."""
    from unittest.mock import MagicMock

    # Redirect all paths under tmp_path
    fake_plist = tmp_path / "LaunchAgents" / "com.troah.fanqie-short-story.daily.plist"
    fake_env = tmp_path / "ApplicationSupport" / "fanqie-short-story" / "env"
    fake_log = tmp_path / "Logs" / "fanqie-short-story"
    fake_daemon_run = tmp_path / "bin" / "fanqie-story-run"
    fake_daemon_run.parent.mkdir(parents=True)
    fake_daemon_run.touch()
    monkeypatch.setattr("fanqie_short_story.daemon.PLIST_PATH", fake_plist)
    monkeypatch.setattr("fanqie_short_story.daemon.ENV_FILE", fake_env)
    monkeypatch.setattr("fanqie_short_story.daemon.LOG_DIR", fake_log)
    monkeypatch.setattr("fanqie_short_story.daemon.DAEMON_RUN_SCRIPT", fake_daemon_run)
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test-key")
    # Record subprocess.run calls so we can assert launchctl was invoked
    # correctly, without actually spawning launchctl.
    fake_run = MagicMock(return_value=None)
    monkeypatch.setattr("fanqie_short_story.daemon.subprocess.run", fake_run)

    install(
        schedule_time="06:00",
        scorer_root=tmp_path / "scorer",
        fanqie_story_root=tmp_path / "story",
    )

    assert fake_plist.exists()
    plist_text = fake_plist.read_text(encoding="utf-8")
    assert "com.troah.fanqie-short-story.daily" in plist_text
    assert "FANQIE_SCORER_ROOT" in plist_text
    assert "FANQIE_STORY_ROOT" in plist_text
    assert fake_env.exists()
    assert parse_env_file(fake_env)["MINIMAX_API_KEY"] == "sk-test-key"
    # launchctl load -w <fake_plist> was the only subprocess call.
    fake_run.assert_called_once()
    called_argv = fake_run.call_args.args[0]
    assert called_argv == ["launchctl", "load", "-w", str(fake_plist)]


def test_uninstall_unloads_and_removes_plist(tmp_path: Path, monkeypatch) -> None:
    """uninstall() calls launchctl unload + removes the plist file."""
    from fanqie_short_story.daemon import uninstall
    fake_plist = tmp_path / "LaunchAgents" / "com.troah.fanqie-short-story.daily.plist"
    fake_plist.parent.mkdir(parents=True)
    fake_plist.write_text("<?xml ...?>", encoding="utf-8")
    monkeypatch.setattr("fanqie_short_story.daemon.PLIST_PATH", fake_plist)
    subprocess_calls: list[list[str]] = []
    monkeypatch.setattr(
        "fanqie_short_story.daemon.subprocess.run",
        lambda args, **kw: subprocess_calls.append(args),
    )

    uninstall()

    assert not fake_plist.exists()
    assert any("unload" in str(c) for c in subprocess_calls)


def test_status_returns_installed_false_when_no_plist(tmp_path: Path, monkeypatch) -> None:
    """Fresh state (no plist, no env, no DB) → installed=False, env_key_present=False."""
    from fanqie_short_story.daemon import status
    monkeypatch.setattr("fanqie_short_story.daemon.PLIST_PATH", tmp_path / "nope.plist")
    monkeypatch.setattr("fanqie_short_story.daemon.ENV_FILE", tmp_path / "nope-env")
    monkeypatch.setattr(
        "fanqie_short_story.daemon.subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 1, "stderr": b"", "stdout": b""})(),
    )
    report = status()
    assert report.installed is False
    assert report.loaded is False
    assert report.env_key_present is False
    # Spec §3.2 contract: status() always reports the plist_path (even when not installed)
    assert report.plist_path == tmp_path / "nope.plist"


def test_status_returns_last_run_log_path(tmp_path: Path, monkeypatch) -> None:
    """When log_dir has files, status reports the newest log path."""
    from fanqie_short_story.daemon import status
    fake_log = tmp_path / "Logs"
    fake_log.mkdir(parents=True)
    (fake_log / "daily-2026-07-15.log").write_text("old", encoding="utf-8")
    (fake_log / "daily-2026-07-16.log").write_text("new", encoding="utf-8")
    monkeypatch.setattr("fanqie_short_story.daemon.LOG_DIR", fake_log)
    monkeypatch.setattr("fanqie_short_story.daemon.PLIST_PATH", tmp_path / "nope.plist")
    monkeypatch.setattr("fanqie_short_story.daemon.ENV_FILE", tmp_path / "nope-env")
    monkeypatch.setattr(
        "fanqie_short_story.daemon.subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 1, "stderr": b"", "stdout": b""})(),
    )
    report = status()
    assert report.last_run_log is not None
    assert report.last_run_log.name == "daily-2026-07-16.log"


def test_run_once_subprocess_returns_exit_code(monkeypatch) -> None:
    """run_once() invokes the daily CLI in-process and returns its exit code."""
    from fanqie_short_story.daemon import run_once
    fake_cli = MagicMock()
    fake_cli.side_effect = SystemExit(1)
    monkeypatch.setattr("fanqie_short_story.daemon._cli_main", fake_cli)

    rc = run_once(
        config_path=Path("config/defaults.yaml"),
        log_dir=Path("/tmp/logs"),
        scorer_root="/tmp/scorer",
    )
    assert rc == 1
    # It should pass standalone_mode=False + the 'daily run-once --config <path>' args via kwargs
    args, kwargs = fake_cli.call_args
    assert kwargs.get("args") == [
        "daily", "run-once", "--config", str(Path("config/defaults.yaml")),
    ]
    assert kwargs.get("standalone_mode") is False


def test_run_once_writes_log_file_under_log_dir(tmp_path: Path, monkeypatch) -> None:
    """Spec §3.2: run_once() tees stdout/stderr to log_dir/daily-<date>.log.

    The mock _cli_main writes a sentinel to sys.stdout; we assert the sentinel
    lands in the log file. This catches regressions where redirect_stdout
    fails to capture Click's echo() output (e.g., if a future change uses
    `sys.__stdout__` directly or if Click caches output streams).
    """
    import sys
    from datetime import date
    from fanqie_short_story.daemon import run_once

    def fake_cli_main(*, args, standalone_mode):
        # Inside the redirected context, sys.stdout points at the log file.
        sys.stdout.write("SENTINEL_FROM_CLI\n")
        sys.stdout.flush()

    monkeypatch.setattr("fanqie_short_story.daemon._cli_main", fake_cli_main)

    rc = run_once(
        config_path=Path("config/defaults.yaml"),
        log_dir=tmp_path,
        scorer_root="/tmp/scorer",
    )
    assert rc == 0
    expected_log = tmp_path / f"daily-{date.today().isoformat()}.log"
    assert expected_log.exists()
    content = expected_log.read_text(encoding="utf-8")
    assert "SENTINEL_FROM_CLI" in content


def test_run_with_notification_loads_env_and_returns_rc(tmp_path: Path, monkeypatch) -> None:
    """Loads MINIMAX_API_KEY from ENV_FILE if not in env; runs the in-process
    scan (here mocked to return 0); fires osascript (mocked to no-op); returns 0."""
    from fanqie_short_story.daemon import run_with_notification
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake_env = tmp_path / "env"
    fake_env.write_text("MINIMAX_API_KEY=sk-from-disk\n", encoding="utf-8")
    monkeypatch.setattr("fanqie_short_story.daemon.ENV_FILE", fake_env)
    monkeypatch.setattr(
        "fanqie_short_story.daemon._run_scan_in_process", lambda: 0,
    )
    monkeypatch.setattr(
        "fanqie_short_story.daemon._fire_osascript", lambda *a, **kw: 0,
    )
    rc = run_with_notification()
    assert rc == 0
    assert os.environ.get("MINIMAX_API_KEY") == "sk-from-disk"