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


_REQUIRED_CSV_COLUMNS = frozenset({"rank", "book_id", "title", "author", "genre", "overall", "rationale"})


def load_top_n(csv_path: Path, n: int, *, scorer_root: Path) -> list[RankedBook]:
    """Parse scores.csv, take first n rows by rank, return RankedBook list.

    synopsis is joined in from the SQLite DB at scorer_root/output/fanqie.db
    via topic-scorer's `books` table (see _lookup_synopses for the soft-fallback
    contract: missing row → synopsis == title; missing table/column → DailyRunError).
    """
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = _REQUIRED_CSV_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"scores.csv missing required columns: {sorted(missing)}"
            )
        rows = list(reader)

    # Build a book_id → synopsis lookup once, then merge.
    synopses = _lookup_synopses(scorer_root, [r["book_id"] for r in rows])

    out: list[RankedBook] = []
    for row in rows[:n]:
        book_id = row["book_id"]
        title = row["title"]
        out.append(
            RankedBook(
                rank=int(row["rank"]),
                book_id=book_id,
                title=title,
                author=row["author"],
                synopsis=synopses.get(book_id, title),  # soft fallback to title
                genre=row["genre"],
                overall=float(row["overall"]),
                rationale=row["rationale"],
            )
        )
    return out


def _lookup_synopses(scorer_root: Path, book_ids: list[str]) -> dict[str, str]:
    """Query scorer_root/output/fanqie.db `books` table for synopses.

    Returns {book_id: synopsis}. Missing entries (row absent or NULL synopsis)
    are absent from the result — caller falls back to title.

    Hard fails (raise DailyRunError with diagnostic):
      - DB file missing
      - `books` table missing
      - `synopsis` column missing
    """
    db_path = scorer_root / "output" / "fanqie.db"
    if not db_path.exists():
        raise DailyRunError(
            f"schema drift detected in {db_path}: file missing.\n"
            f"  See fanqie-topic-scorer docs at "
            f"docs/superpowers/specs/2026-07-14-fanqie-topic-scorer-design.md"
        )
    unique_ids = list(dict.fromkeys(book_ids))  # preserve order, dedupe
    placeholders = ",".join("?" * len(unique_ids))
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.execute(
                f"SELECT book_id, synopsis FROM books WHERE book_id IN ({placeholders})",
                unique_ids,
            )
            return {
                bid: syn
                for bid, syn in cur.fetchall()
                if syn  # drop NULL/empty
            }
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "no such table" in msg and "books" in msg:
            raise DailyRunError(
                f"schema drift detected in {db_path}: missing 'books' table.\n"
                f"  See fanqie-topic-scorer docs at "
                f"docs/superpowers/specs/2026-07-14-fanqie-topic-scorer-design.md"
            ) from e
        if "no such column" in msg and "synopsis" in msg:
            raise DailyRunError(
                f"schema drift detected in {db_path}: missing 'books.synopsis' column.\n"
                f"  See fanqie-topic-scorer docs at "
                f"docs/superpowers/specs/2026-07-14-fanqie-topic-scorer-design.md"
            ) from e
        raise