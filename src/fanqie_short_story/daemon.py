"""Daemon layer: macOS launchd integration for daily story generation.

Spec: docs/superpowers/specs/2026-07-16-fanqie-short-story-v0.3.0-daily-automation-design.md

This module is the single owner of:
  - the LaunchAgent plist template (Python `string.Template`)
  - the env-file I/O (XDG-style ~/Library/Application Support/.../env, chmod 600)
  - the plist install/unload lifecycle (`install`, `uninstall`)
  - the `status()` snapshot used by the `daemon status` Click subcommand
  - `run_with_notification()`, the entry point called by the
    `fanqie-story-run` console script registered in pyproject.toml
"""
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from string import Template


# ---------------------------------------------------------------------------
# Constants (spec §3.2)
# ---------------------------------------------------------------------------

LABEL: str = "com.troah.fanqie-short-story.daily"
PLIST_PATH: Path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
ENV_FILE: Path = (
    Path.home() / "Library" / "Application Support" / "fanqie-short-story" / "env"
)
LOG_DIR: Path = Path.home() / "Library" / "Logs" / "fanqie-short-story"
DAEMON_RUN_SCRIPT: Path = Path(sys.executable).parent / "fanqie-story-run"

# Marker env var: plist sets FANQIE_STORY_DAEMON=1 in its process env.
DAEMON_ENV_VAR: str = "FANQIE_STORY_DAEMON"

# Permissions (avoid leaking the API key via `ls -la`).
ENV_FILE_MODE: int = 0o600
DIR_MODE_USER_ONLY: int = 0o700


# ---------------------------------------------------------------------------
# Plist template (spec §3.2)
# ---------------------------------------------------------------------------

PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>               <string>$label</string>
    <key>ProgramArguments</key>    <array><string>$daemon_run</string></array>
    <key>StartCalendarInterval</key><dict>
        <key>Hour</key>   <integer>$hour</integer>
        <key>Minute</key> <integer>$minute</integer>
    </dict>
    <key>LaunchOnDemand</key>      <false/>
    <key>RunAtLoad</key>           <false/>
    <key>ThrottleInterval</key>    <integer>3600</integer>
    <key>EnvironmentVariables</key><dict>
        <key>$daemon_env_var</key>          <string>1</string>
        <key>FANQIE_SCORER_ROOT</key>       <string>$scorer_root</string>
        <key>FANQIE_STORY_ROOT</key>        <string>$fanqie_story_root</string>
    </dict>
    <key>StandardOutPath</key>     <string>$log_dir/daily.out</string>
    <key>StandardErrorPath</key>   <string>$log_dir/daily.err</string>
</dict>
</plist>
"""


# ---------------------------------------------------------------------------
# Pure functions (testable without I/O)
# ---------------------------------------------------------------------------

def _parse_schedule(schedule_time: str) -> tuple[int, int]:
    """Parse 'HH:MM' → (hour, minute). Raises ValueError on bad format."""
    parts = schedule_time.split(":")
    if len(parts) != 2:
        raise ValueError(f"schedule_time must be HH:MM, got {schedule_time!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"schedule_time out of range: {schedule_time!r}")
    return hour, minute


def render_plist(
    *,
    schedule_time: str = "06:00",
    log_dir: Path,
    scorer_root: Path,
    fanqie_story_root: Path,
    label: str = LABEL,
    daemon_run: Path = DAEMON_RUN_SCRIPT,
    daemon_env_var: str = DAEMON_ENV_VAR,
) -> str:
    """Render the LaunchAgent plist XML. Pure function: no I/O."""
    hour, minute = _parse_schedule(schedule_time)
    return Template(PLIST_TEMPLATE).substitute(
        label=label,
        daemon_run=str(daemon_run),
        hour=hour,
        minute=minute,
        log_dir=str(log_dir),
        scorer_root=str(scorer_root),
        fanqie_story_root=str(fanqie_story_root),
        daemon_env_var=daemon_env_var,
    )


def run_with_notification() -> int:
    """Placeholder — Chunk 3 replaces this body."""
    raise NotImplementedError(
        "run_with_notification is implemented in Chunk 3 (Task 12)"
    )