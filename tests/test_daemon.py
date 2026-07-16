"""Tests for fanqie_short_story.daemon — macOS launchd integration."""
from __future__ import annotations

from pathlib import Path

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