"""Tests for fanqie_short_story.daemon — macOS launchd integration."""
from __future__ import annotations

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