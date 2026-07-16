"""Daily automated story-generation orchestrator.

Spec: docs/superpowers/specs/2026-07-16-fanqie-short-story-v0.3.0-daily-automation-design.md
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from random import Random

from filelock import FileLock, Timeout

from fanqie_short_story.config import Config
from fanqie_short_story.manifest import StoryManifest
from fanqie_short_story.pipeline import GenerationFailed, generate_story


# Module-level constants (spec §3.5)
LOCK_PATH: Path = Path.home() / ".local" / "share" / "fanqie-short-story" / "daily.lock"
LOCK_TIMEOUT_SECONDS: int = 300  # 5 min — generous for a 5-story run

DEFAULT_SCORER_ROOT: Path = Path.home() / "CascadeProjects" / "projects" / "fanqie-topic-scorer"


class DailyRunError(RuntimeError):
    """Raised on hard-fail conditions (schema drift, lock timeout)."""


@dataclass
class RankedBook:
    rank: int
    book_id: str
    title: str
    author: str
    synopsis: str  # joined from SQLite, or fallback to title (see _lookup_synopses)
    genre: str
    overall: float
    rationale: str


@dataclass
class DailyRunResult:
    date: str                       # YYYY-MM-DD
    source_csv: Path
    generated: list[Path] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    api_calls: int = 0


def find_latest_scores_csv(scorer_root: Path) -> Path:
    """Return the newest scores.csv under <scorer_root>/output/runs/*/.

    Raises FileNotFoundError if no scores.csv exists.
    """
    runs_dir = scorer_root / "output" / "runs"
    if not runs_dir.is_dir():
        raise FileNotFoundError(
            f"no scores.csv under {scorer_root}: {runs_dir} does not exist"
        )
    candidates = list(runs_dir.glob("*/scores.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"no scores.csv under {scorer_root} (looked in {runs_dir}/*/scores.csv)"
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)