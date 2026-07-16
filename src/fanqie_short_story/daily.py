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


def run_daily(
    *,
    config: Config,
    scorer_root: Path,
    output_root: Path,
    top_n: int = 5,
    max_substitute_depth: int = 7,
    shuffle_seed: int | None = None,
) -> DailyRunResult:
    """Top-level orchestrator. Acquires the file lock, picks latest CSV,
    loads top_n+max_substitute_depth books, shuffles priority order, generates
    up to top_n stories with substitute fallback, returns DailyRunResult.

    NOT a CLI entry — see cli.py for that. DailyRunError propagates from
    _lookup_synopses (schema drift); FileNotFoundError from find_latest_scores_csv.
    """
    lock = FileLock(LOCK_PATH, timeout=LOCK_TIMEOUT_SECONDS)
    try:
        with lock:
            return _run_daily_unlocked(
                config=config,
                scorer_root=scorer_root,
                output_root=output_root,
                top_n=top_n,
                max_substitute_depth=max_substitute_depth,
                shuffle_seed=shuffle_seed,
            )
    except Timeout as e:
        raise DailyRunError(
            f"another daily run is in flight (lock held >{LOCK_TIMEOUT_SECONDS}s); "
            f"refusing to run concurrently. If you believe this is stale, "
            f"check {LOCK_PATH} and remove it manually."
        ) from e


def _run_daily_unlocked(
    *,
    config: Config,
    scorer_root: Path,
    output_root: Path,
    top_n: int,
    max_substitute_depth: int,
    shuffle_seed: int | None,
) -> DailyRunResult:
    csv_path = find_latest_scores_csv(scorer_root)
    pool_size = top_n + max_substitute_depth
    books = load_top_n(csv_path, n=pool_size, scorer_root=scorer_root)
    if not books:
        return DailyRunResult(
            date=datetime.now().date().isoformat(), source_csv=csv_path,
        )

    started_at = time.monotonic()

    priority = books[:top_n]
    extras = books[top_n:]
    rng = Random(shuffle_seed) if shuffle_seed is not None else Random()
    rng.shuffle(priority)
    pool = priority + extras

    output_root.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    result = DailyRunResult(date=today, source_csv=csv_path)
    stories_dir = output_root / today / "stories"
    stories_dir.mkdir(parents=True, exist_ok=True)

    attempts = 0
    while attempts < top_n and pool:
        book = pool.pop(0)
        # Translate the scorer's fine-grained sub-genre (e.g. "xuanhuan-xiuzhen")
        # to the umbrella genre the pipeline understands ("chuanqi"). Mirrors
        # what `batch` CLI has done since v0.1.0. Unmapped genres pass through
        # unchanged so callers with already-umbrella labels still work.
        mapped_genre = config.genre_mapping.get(book.genre, book.genre)
        try:
            out = generate_story(
                hook=book.synopsis,
                genre=mapped_genre,
                target_length=12000,
                tone=None,
                output_dir=stories_dir,
                slug=_slugify_daily(book.title, book.author),
                config=config,
            )
            _stamp_daily_meta(out, book)
            result.generated.append(out)
            result.api_calls += _read_manifest_llm_calls(out)
            attempts += 1
        except (GenerationFailed, FileExistsError) as e:
            result.failures.append({
                "rank": book.rank,
                "title": book.title,
                "reason": str(e),
                "traceback_excerpt": None,
            })
        except Exception as e:
            result.failures.append({
                "rank": book.rank,
                "title": book.title,
                "reason": type(e).__name__ + ": " + str(e),
                "traceback_excerpt": traceback.format_exc(limit=3),
            })
    elapsed = int(time.monotonic() - started_at)
    write_daily_manifest(
        output_root / today,
        result,
        top_n_requested=top_n,
        substitute_pool_size=max_substitute_depth,
        duration_seconds=elapsed,
    )
    return result


_DAILY_SLUG_RE = re.compile(r"[^\w]+", re.UNICODE)


def _slugify_daily(title: str, author: str) -> str:
    """Slug = <title>-<author>, filesystem-safe, max 60 chars total."""
    s = _DAILY_SLUG_RE.sub("-", f"{title}-{author}").strip("-")
    return s[:60] or "story"


def _read_manifest_llm_calls(story_dir: Path) -> int:
    """Read story_dir/manifest.json and return its `llm_calls` field. 0 if missing."""
    manifest_path = story_dir / "manifest.json"
    if not manifest_path.exists():
        return 0
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return int(json.load(f).get("llm_calls", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def _stamp_daily_meta(story_dir: Path, book: RankedBook) -> None:
    """Add daily_rank/daily_title/daily_author to the story's manifest.json."""
    manifest_path = story_dir / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    data["daily_rank"] = book.rank
    data["daily_title"] = book.title
    data["daily_author"] = book.author
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_WEEK_RE = re.compile(r"(\d{4}-W\d{2})")


def write_daily_manifest(
    output_dir: Path,
    result: DailyRunResult,
    *,
    top_n_requested: int = 5,
    substitute_pool_size: int = 7,
    duration_seconds: int = 0,
) -> Path:
    """Write output_dir/daily_manifest.json. Returns the manifest path.

    Schema (spec §6):
      - date, source_csv, source_csv_mtime, source_csv_week, scorer_root
      - top_n_requested, substitute_pool_size
      - generated: list of {rank, title, author, slug, story_dir,
                            manifest_path, critique_strategy,
                            accepted_after_critic_cap, llm_calls, char_count}
      - failures: list of {rank, title, reason, traceback_excerpt}
      - totals: {succeeded, failed, api_calls, duration_seconds}

    `top_n_requested`, `substitute_pool_size`, and `duration_seconds` are
    passed in by `_run_daily_unlocked` (which knows the actual values used).
    The defaults (5 / 7 / 0) keep the function independently callable for
    tests and one-off manual manifest regeneration.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    mtime = datetime.fromtimestamp(result.source_csv.stat().st_mtime, tz=timezone.utc)
    week_match = _WEEK_RE.search(result.source_csv.parent.name)
    week = week_match.group(1) if week_match else "unknown"

    generated_entries = []
    for path in result.generated:
        manifest_path = path / "manifest.json"
        meta = _read_story_manifest_meta(manifest_path)
        generated_entries.append({
            "rank": meta.get("daily_rank"),
            "title": meta.get("daily_title"),
            "author": meta.get("daily_author"),
            "slug": path.name,
            "story_dir": str(path),
            "manifest_path": str(manifest_path),
            "critique_strategy": meta.get("critique_strategy", "unknown"),
            "accepted_after_critic_cap": meta.get("accepted_after_critic_cap", False),
            "llm_calls": meta.get("llm_calls", 0),
            "char_count": meta.get("actual_length", 0),
        })

    payload = {
        "date": result.date,
        "source_csv": str(result.source_csv),
        "source_csv_mtime": mtime.isoformat(),
        "source_csv_week": week,
        "scorer_root": str(result.source_csv.parent.parent.parent.parent),
        "top_n_requested": top_n_requested,
        "substitute_pool_size": substitute_pool_size,
        "generated": generated_entries,
        "failures": result.failures,
        "totals": {
            "succeeded": len(result.generated),
            "failed": len(result.failures),
            "api_calls": result.api_calls,
            "duration_seconds": duration_seconds,
        },
    }
    out_path = output_dir / "daily_manifest.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return out_path


def _read_story_manifest_meta(manifest_path: Path) -> dict:
    """Read a story's manifest.json and return a flat dict. Empty on miss."""
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}