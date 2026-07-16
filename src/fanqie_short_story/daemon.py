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


def _cli_main(*args, **kwargs):
    """Local indirection so tests can monkeypatch without importing click."""
    from fanqie_short_story.cli import main as _real_main
    return _real_main(*args, **kwargs)


def run_once(
    *,
    config_path: Path,
    log_dir: Path,
    scorer_root: str,
) -> int:
    """Subprocess invocation point for plist. Runs `fanqie-story daily run-once`,
    pipes output to log_dir/daily-<date>.log, exits with the inner command's exit code.

    File lock acquisition is handled inside `daily.run_daily()` (spec §3.5).

    Note on append mode: the LOG file uses `"a"` (append), not `"w"` (overwrite).
    The MANIFEST (`daily_manifest.json`) is overwritten by `write_daily_manifest`
    because it's a structured snapshot of the latest run state. The LOG is a
    chronological journal — appending preserves partial output from a crashed
    run, lets a manual run and a launchd run co-exist in the same file, and
    matches the standard convention for `daily-<date>.log` files.
    """
    # The daily CLI subcommand handles its own logging via Click; we just need
    # to ensure the env has the right paths, open the per-day log file, and
    # invoke the CLI in-process with stdout/stderr redirected to it.
    if scorer_root:
        os.environ.setdefault("FANQIE_SCORER_ROOT", scorer_root)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"daily-{_date.today().isoformat()}.log"
    cli_args = ["daily", "run-once", "--config", str(config_path)]
    try:
        with open(log_path, "a", encoding="utf-8") as logf:
            with redirect_stdout(logf), redirect_stderr(logf):
                _cli_main(args=cli_args, standalone_mode=False)
        return 0
    except SystemExit as exc:
        return int(getattr(exc, "code", 0) or 0)


def _run_scan_in_process() -> int:
    """Invoke the daily run-once command in-process. Returns its exit code.

    CRITICAL: Click groups with standalone_mode=False resolve no-args to
    --help (exit 0) by default. We MUST pass args=['daily', 'run-once']
    explicitly or launchd will print help every day at 06:00 and exit 0
    with nothing to score.
    """
    return run_once(
        config_path=Path("config/defaults.yaml"),
        log_dir=LOG_DIR,
        scorer_root=os.environ.get("FANQIE_SCORER_ROOT", ""),
    )


def _fire_osascript(title: str, subtitle: str, message: str) -> int:
    """osascript notification with argv-passed values (no string injection)."""
    script = (
        "on run {msg, ttl, sub}\n"
        "display notification msg with title ttl subtitle sub\n"
        "end run"
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script, message, title, subtitle],
            capture_output=True, check=False,
        )
        return out.returncode
    except FileNotFoundError:
        return 127


def run_with_notification() -> int:
    """Launchd entry point (called by `fanqie-story-run`).

    Sequence (spec §3.2 + §5):
      1. Load MINIMAX_API_KEY from ENV_FILE into os.environ if not already set.
      2. Run the daily run-once command in-process.
      3. If failed, write a one-line stderr summary BEFORE the osascript so
         the launchd log has actionable info, not just "exit 1".
      4. Fire osascript notification (always, even on failure).
      5. Return the original exit code.
    """
    # 1. Load API key from disk if missing in this process's env.
    if not (os.environ.get("MINIMAX_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        if ENV_FILE.exists():
            for k, v in parse_env_file(ENV_FILE).items():
                os.environ.setdefault(k, v)

    # 2. Run.
    rc = _run_scan_in_process()

    # 3. Stderr on failure.
    if rc != 0:
        sys.stderr.write(f"daemon: daily run-once exited {rc}; see logs\n")

    # 4. Build + fire notification (spec §5 osascript messages).
    today = datetime.now().date().isoformat()
    if rc == 0:
        title = "番茄短篇完成"
        message = f"{today}: 5 篇生成完"
    else:
        title = "番茄短篇失败"
        message = f"{today}: exit {rc} · 见 ~/Library/Logs/fanqie-short-story/daily.err"
    _fire_osascript(title, "", message)

    return rc


def parse_env_file(path: Path) -> dict[str, str]:
    """Read a KEY=VALUE env file. Tolerates blanks, comments, single/double quotes.

    Empty lines and comment-only lines are silently ignored. Malformed lines
    (no `=`) are skipped (matches the dotenv ecosystem convention).
    """
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def write_env_file(path: Path, env: dict[str, str]) -> None:
    """Write atomically: write to <path>.tmp, fsync, rename onto path. chmod 0o600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(f"{k}={v}" for k, v in env.items()) + "\n"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    os.chmod(path, ENV_FILE_MODE)


def write_plist(plist_xml: str, dest: Path, *, force: bool = False) -> None:
    """Write the plist, creating parent dir. Refuse to overwrite unless force=True."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        existing = dest.read_text(encoding="utf-8")
        if existing == plist_xml:
            return
        raise FileExistsError(
            f"{dest} exists with different content; pass force=True to overwrite"
        )
    dest.write_text(plist_xml, encoding="utf-8")


def install(
    *,
    schedule_time: str,
    scorer_root: Path,
    fanqie_story_root: Path,
    force: bool = False,
    update_env: bool = False,
) -> None:
    """Idempotent install (spec §3.2 `install`).

    Steps (each short-circuits the next on failure):
      0. confirm `fanqie-story-run` console script exists on disk
      1. ensure LOG_DIR exists (chmod 0o700)
      2. ensure ENV_FILE.parent exists (chmod 0o700)
      3. if update_env OR env file missing: persist the API key
      4. render the plist; refuse overwrite unless force=True
      5. subprocess: launchctl load -w <PLIST_PATH>
    """
    if not DAEMON_RUN_SCRIPT.exists():
        raise FileNotFoundError(
            f"could not find {DAEMON_RUN_SCRIPT} — activate your venv "
            f"and re-run `pip install -e .` to register the console script."
        )

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(LOG_DIR, DIR_MODE_USER_ONLY)
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ENV_FILE.parent, DIR_MODE_USER_ONLY)

    need_key_write = update_env or not ENV_FILE.exists()
    if need_key_write:
        # MINIMAX_API_KEY (canonical) → ANTHROPIC_API_KEY (legacy fallback).
        key = (
            os.environ.get("MINIMAX_API_KEY", "").strip()
            or os.environ.get("ANTHROPIC_API_KEY", "").strip()
        )
        if not key:
            from fanqie_short_story.config import ConfigError
            raise ConfigError(
                "No API key in environment. Set MINIMAX_API_KEY (preferred) "
                "or ANTHROPIC_API_KEY (legacy fallback) before running "
                "`daemon install`."
            )
        write_env_file(ENV_FILE, {"MINIMAX_API_KEY": key})

    plist_xml = render_plist(
        schedule_time=schedule_time,
        log_dir=LOG_DIR,
        scorer_root=scorer_root,
        fanqie_story_root=fanqie_story_root,
    )
    write_plist(plist_xml, PLIST_PATH, force=force)

    subprocess.run(
        ["launchctl", "load", "-w", str(PLIST_PATH)],
        check=True,
    )


@dataclass
class StatusReport:
    """One-screen snapshot for `fanqie-story daemon status` (spec §3.2)."""
    installed: bool        # plist file exists on disk
    loaded: bool           # launchctl knows about LABEL
    plist_path: Path       # where the plist lives (spec §3.2 status() contract)
    schedule_time: str     # HH:MM, parsed from plist (or default)
    env_key_present: bool  # env file exists & has non-empty MINIMAX_API_KEY
    last_run_log: Path | None


def uninstall() -> None:
    """Tolerate 'service not loaded' from launchctl; always remove the plist.
    Leaves ENV_FILE alone so re-install doesn't require a new key."""
    try:
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            check=True,
        )
    except subprocess.CalledProcessError:
        pass
    except FileNotFoundError:
        pass  # launchctl not on PATH
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()


def _find_latest_log() -> Path | None:
    """Newest file in LOG_DIR matching daily-*.log, or None."""
    if not LOG_DIR.is_dir():
        return None
    candidates = sorted(LOG_DIR.glob("daily-*.log"))
    return candidates[-1] if candidates else None


def _read_schedule_time_from_plist() -> str:
    """Best-effort parse of Hour/Minute from the plist. Returns '06:00' on miss."""
    if not PLIST_PATH.exists():
        return "06:00"
    text = PLIST_PATH.read_text(encoding="utf-8")
    import re as _re
    hour_m = _re.search(r"<key>Hour</key>\s*<integer>(\d+)</integer>", text)
    minute_m = _re.search(r"<key>Minute</key>\s*<integer>(\d+)</integer>", text)
    if hour_m and minute_m:
        return f"{int(hour_m.group(1)):02d}:{int(minute_m.group(1)):02d}"
    return "06:00"


def status() -> StatusReport:
    """Snapshot the daemon state for `daemon status` (spec §3.2).

    Tolerates missing plist / env file / LOG_DIR — the report is informative
    even on a fresh install. Public signature is parameterless; tests reach
    in via monkeypatch on the module-level constants.
    """
    installed = PLIST_PATH.exists()

    loaded = False
    try:
        out = subprocess.run(
            ["launchctl", "list", LABEL],
            capture_output=True, check=False,
        )
        loaded = out.returncode == 0
    except FileNotFoundError:
        loaded = False

    schedule_time = _read_schedule_time_from_plist()

    env_key_present = False
    if ENV_FILE.exists():
        try:
            env = parse_env_file(ENV_FILE)
            env_key_present = bool(env.get("MINIMAX_API_KEY", "").strip())
        except OSError:
            env_key_present = False

    return StatusReport(
        installed=installed,
        loaded=loaded,
        plist_path=PLIST_PATH,
        schedule_time=schedule_time,
        env_key_present=env_key_present,
        last_run_log=_find_latest_log(),
    )