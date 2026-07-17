"""Tests for fanqie_short_story.daily — daily orchestrator."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest
from filelock import FileLock

from unittest.mock import MagicMock, patch

from fanqie_short_story.daily import (
    DailyRunError,
    DailyRunResult,
    LOCK_PATH,
    LOCK_TIMEOUT_SECONDS,
    _lookup_synopses,
    find_latest_scores_csv,
    load_top_n,
    run_daily,
    write_daily_manifest,
)
import fanqie_short_story.daily as daily_mod
from fanqie_short_story.pipeline import GenerationFailed


def test_find_latest_scores_csv_returns_newest(tmp_path: Path) -> None:
    """Two CSVs at different mtimes — return the newer."""
    runs = tmp_path / "output" / "runs"
    w1 = runs / "2026-W28"
    w2 = runs / "2026-W29"
    w1.mkdir(parents=True)
    w2.mkdir(parents=True)
    older = w1 / "scores.csv"
    newer = w2 / "scores.csv"
    older.write_text("rank,book_id\n1,a\n", encoding="utf-8")
    newer.write_text("rank,book_id\n1,b\n", encoding="utf-8")
    # Force distinct mtimes (filesystem granularity can be coarse on macOS)
    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time(), time.time()))

    result = find_latest_scores_csv(tmp_path)
    assert result == newer


def test_find_latest_scores_csv_raises_when_none(tmp_path: Path) -> None:
    """No scores.csv under scorer_root → FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="scores.csv"):
        find_latest_scores_csv(tmp_path)


CSV_HEADER = "rank,book_id,title,author,genre,chapters_count,in_read,overall,dim_hook,dim_plot,rationale\n"
CSV_ROW = "1,abc123,凡骨,壹,xuanhuan,120,1,8.2,7,8,test rationale\n"


def _write_csv(path: Path, n: int) -> Path:
    """Write a scores.csv with n fake rows."""
    rows = []
    for i in range(1, n + 1):
        rows.append(
            f"{i},id{i},title{i},author{i},xuanhuan,100,1,7.0,7,7,rationale-{i}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CSV_HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_load_top_n_parses_csv(tmp_path: Path) -> None:
    """Parse scores.csv, take first n rows by rank, return RankedBook list."""
    csv_path = _write_csv(tmp_path / "scores.csv", n=3)
    # Schema present but no synopsis rows → every book_id hits the row-missing
    # soft fallback (synopsis == title). Spec §3.4: a *missing DB file* is a
    # hard fail, so the DB must exist for the fallback path to be exercised.
    _create_topic_scorer_db(tmp_path, with_synopsis_col=True, populate_synopses=False)
    result = load_top_n(csv_path, n=2, scorer_root=tmp_path)
    assert len(result) == 2
    assert result[0].rank == 1
    assert result[0].title == "title1"
    assert result[0].synopsis == "title1"  # row-missing soft fallback
    assert result[0].genre == "xuanhuan"
    assert result[0].overall == pytest.approx(7.0)


def test_load_top_n_returns_n_rows_or_all(tmp_path: Path) -> None:
    """CSV has 3 rows, n=10 → 3 rows returned."""
    csv_path = _write_csv(tmp_path / "scores.csv", n=3)
    _create_topic_scorer_db(tmp_path, with_synopsis_col=True, populate_synopses=False)
    result = load_top_n(csv_path, n=10, scorer_root=tmp_path)
    assert len(result) == 3


def test_load_top_n_raises_on_missing_columns(tmp_path: Path) -> None:
    """Malformed CSV (missing 'genre' column) → ValueError."""
    bad = tmp_path / "scores.csv"
    bad.write_text("rank,book_id,title\n1,a,t\n", encoding="utf-8")
    with pytest.raises(ValueError, match="genre"):
        load_top_n(bad, n=5, scorer_root=tmp_path)


def _create_topic_scorer_db(
    scorer_root: Path, *, with_synopsis_col: bool = True, populate_synopses: bool = True
) -> Path:
    """Build a fake fanqie.db with `books` table (optionally w/o synopsis col).

    When `populate_synopses=True`, seeds two rows: id1 with a real synopsis,
    id2 with NULL (so the spec §3.4 NULL-synopsis soft-fallback is testable).
    When `populate_synopses=False`, only the schema is created — every `book_id`
    query will hit the row-missing soft-fallback (title-as-hook). Used by tests
    like the shuffle test, where every book's hook must equal its title.
    """
    db_path = scorer_root / "output" / "fanqie.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        if with_synopsis_col:
            conn.execute(
                "CREATE TABLE books (book_id TEXT PRIMARY KEY, synopsis TEXT)"
            )
            if populate_synopses:
                conn.executemany(
                    "INSERT INTO books VALUES (?, ?)",
                    [("id1", "synopsis of book 1"), ("id2", None)],
                )
        else:
            conn.execute("CREATE TABLE books (book_id TEXT PRIMARY KEY)")
    return db_path


def test_load_top_n_looks_up_synopses_in_sqlite(tmp_path: Path) -> None:
    """Spec §8 item 6: when `books.synopsis` is populated, the recovered
    synopsis is used (NOT the title-as-hook fallback)."""
    csv_path = _write_csv(tmp_path / "scores.csv", n=3)
    # Populate the DB so id1 → "synopsis of book 1", id2 → NULL, id3 → missing.
    _create_topic_scorer_db(tmp_path, with_synopsis_col=True, populate_synopses=True)
    result = load_top_n(csv_path, n=3, scorer_root=tmp_path)
    assert result[0].synopsis == "synopsis of book 1"   # recovered from SQLite
    assert result[1].synopsis == "title2"                # NULL → soft fallback
    assert result[2].synopsis == "title3"                # row missing → soft fallback


# --------------------------------------------------------------------------
# Tests for _lookup_synopses — Task 5 / v0.3.0
# --------------------------------------------------------------------------

def test_lookup_synopses_raises_on_missing_db(tmp_path: Path) -> None:
    """Hard fail: no fanqie.db at all → DailyRunError mentioning the path."""
    with pytest.raises(DailyRunError, match="file missing"):
        _lookup_synopses(tmp_path, ["any"])


def test_lookup_synopses_raises_on_missing_books_table(tmp_path: Path) -> None:
    """Hard fail: DB exists but no `books` table → DailyRunError."""
    db = tmp_path / "output" / "fanqie.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db_path = db
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE other (x INT)")
    with pytest.raises(DailyRunError, match="missing 'books' table"):
        _lookup_synopses(tmp_path, ["any"])


def test_lookup_synopses_raises_on_missing_synopsis_column(tmp_path: Path) -> None:
    """Hard fail: books table exists but no `synopsis` column → DailyRunError."""
    _create_topic_scorer_db(tmp_path, with_synopsis_col=False)
    with pytest.raises(DailyRunError, match="missing 'books.synopsis' column"):
        _lookup_synopses(tmp_path, ["id1"])


def test_lookup_synopses_returns_empty_for_missing_rows(tmp_path: Path) -> None:
    """Soft fallback: books table exists, book_id absent → no entry, no error."""
    _create_topic_scorer_db(tmp_path, with_synopsis_col=True)
    result = _lookup_synopses(tmp_path, ["not-in-db"])
    assert result == {}


def test_lookup_synopses_skips_null_synopsis(tmp_path: Path) -> None:
    """Soft fallback: book_id present but synopsis IS NULL → no entry."""
    _create_topic_scorer_db(tmp_path, with_synopsis_col=True)
    result = _lookup_synopses(tmp_path, ["id1", "id2"])
    assert result == {"id1": "synopsis of book 1"}  # id2's NULL dropped


# --------------------------------------------------------------------------
# Tests for run_daily — Task 6 / v0.3.0
# --------------------------------------------------------------------------

def _make_config(tmp_path: Path) -> MagicMock:
    """Mock Config with the minimum fields run_daily + generate_story touch."""
    cfg = MagicMock()
    cfg.critique = MagicMock()
    return cfg


def _write_topic_scorer_output(scorer_root: Path, n: int) -> Path:
    """Create a fake <scorer_root>/output/runs/<week>/scores.csv with n rows.

    Creates the topic-scorer DB with the `books` table + `synopsis` column but
    WITHOUT populating any synopsis rows. This forces the spec §3.4 soft
    fallback (row-missing → title-as-hook) for every book.
    """
    runs = scorer_root / "output" / "runs" / "2026-W29"
    runs.mkdir(parents=True)
    csv_path = runs / "scores.csv"
    _write_csv(csv_path, n=n)
    _create_topic_scorer_db(scorer_root, with_synopsis_col=True, populate_synopses=False)
    return csv_path


def test_run_daily_generates_5_with_top5_priority(tmp_path: Path) -> None:
    """Happy path: all 5 stories succeed, top-5 selected."""
    scorer = tmp_path / "scorer"
    _write_topic_scorer_output(scorer, n=12)
    out_root = tmp_path / "out"

    with patch("fanqie_short_story.daily.generate_story") as mock_gen:
        mock_gen.return_value = Path("output/stories/foo")
        result = run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=out_root,
            top_n=5,
            max_substitute_depth=7,
        )

    assert len(result.generated) == 5
    assert result.failures == []
    assert mock_gen.call_count == 5


def test_run_daily_substitutes_on_generation_failed(tmp_path: Path) -> None:
    """First-attempt raises GenerationFailed → substitute from extras succeeds."""
    from random import Random as _Random
    scorer = tmp_path / "scorer"
    _write_topic_scorer_output(scorer, n=12)
    out_root = tmp_path / "out"

    call_count = {"n": 0}

    def fake_gen(*, hook, genre, target_length, **_):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise GenerationFailed("boom", output_dir=out_root / "slug1")
        return out_root / f"slug{call_count['n']}"

    expected_first_rank = [1, 2, 3, 4, 5]
    _Random(0).shuffle(expected_first_rank)

    with patch("fanqie_short_story.daily.generate_story", side_effect=fake_gen):
        result = run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=out_root,
            top_n=5,
            max_substitute_depth=7,
            shuffle_seed=0,
        )

    assert len(result.generated) == 5
    assert len(result.failures) == 1
    assert 1 <= result.failures[0]["rank"] <= 5
    assert result.failures[0]["rank"] == expected_first_rank[0]
    assert result.failures[0]["reason"] == "boom"


def test_run_daily_records_traceback_on_unexpected_exception(tmp_path: Path) -> None:
    """Unexpected Exception → failures[].traceback_excerpt populated."""
    scorer = tmp_path / "scorer"
    _write_topic_scorer_output(scorer, n=12)
    out_root = tmp_path / "out"

    def fake_gen(*, hook, genre, target_length, **_):
        if hook == "title1":
            raise ValueError("totally unexpected")
        return out_root / "slug"

    with patch("fanqie_short_story.daily.generate_story", side_effect=fake_gen):
        result = run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=out_root,
            top_n=5,
            max_substitute_depth=7,
        )

    assert len(result.failures) == 1
    assert "totally unexpected" in (result.failures[0]["traceback_excerpt"] or "")


def test_run_daily_stops_when_pool_exhausted(tmp_path: Path) -> None:
    """Pool of 3, all fail → 0 generated, 3 failures."""
    scorer = tmp_path / "scorer"
    _write_topic_scorer_output(scorer, n=3)
    out_root = tmp_path / "out"

    with patch(
        "fanqie_short_story.daily.generate_story",
        side_effect=GenerationFailed("nope", output_dir=out_root / "x"),
    ):
        result = run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=out_root,
            top_n=5,
            max_substitute_depth=0,
        )

    assert len(result.generated) == 0
    assert len(result.failures) == 3


def test_run_daily_shuffles_top5_indices(tmp_path: Path) -> None:
    """Priority order is randomized with a fixed seed; we can predict the shuffle."""
    import random as _random
    scorer = tmp_path / "scorer"
    _write_topic_scorer_output(scorer, n=12)
    out_root = tmp_path / "out"

    captured_titles: list[str] = []

    def fake_gen(*, hook, genre, target_length, **_):
        captured_titles.append(hook)
        return out_root / "slug"

    expected = ["title1", "title2", "title3", "title4", "title5"]
    _random.Random(42).shuffle(expected)

    with patch("fanqie_short_story.daily.generate_story", side_effect=fake_gen):
        run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=out_root,
            top_n=5,
            max_substitute_depth=0,
            shuffle_seed=42,
        )

    assert captured_titles == expected


def test_run_daily_handles_no_scores_csv(tmp_path: Path) -> None:
    """Empty scorer_root → FileNotFoundError propagates from find_latest_scores_csv."""
    scorer = tmp_path / "scorer"
    out_root = tmp_path / "out"

    with pytest.raises(FileNotFoundError, match="scores.csv"):
        run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=out_root,
            top_n=5,
            max_substitute_depth=7,
        )


# --------------------------------------------------------------------------
# Tests for run_daily file lock + api_calls total — Task 7 / v0.3.0
# --------------------------------------------------------------------------


def test_run_daily_acquires_and_releases_lock(tmp_path: Path) -> None:
    """Happy path: lock acquired at start, released at end (file empty after)."""
    scorer = tmp_path / "scorer"
    _write_topic_scorer_output(scorer, n=12)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    with patch("fanqie_short_story.daily.generate_story") as mock_gen:
        mock_gen.return_value = Path("output/stories/x")
        run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=tmp_path / "out",
            top_n=5,
            max_substitute_depth=0,
        )

    # The lock should be released — a second acquisition should succeed immediately
    lock2 = FileLock(LOCK_PATH, timeout=1)
    with lock2:
        pass  # would have raised Timeout if the first lock was still held


def test_run_daily_raises_dailyrunerror_on_lock_timeout(tmp_path: Path, monkeypatch) -> None:
    """Pre-acquire lock from outside; run with tiny timeout → DailyRunError mentioning LOCK_PATH."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    blocker = FileLock(LOCK_PATH, timeout=1)
    blocker.acquire()
    try:
        monkeypatch.setattr(daily_mod, "LOCK_TIMEOUT_SECONDS", 1)
        with pytest.raises(DailyRunError, match=str(LOCK_PATH)):
            run_daily(
                config=_make_config(tmp_path),
                scorer_root=tmp_path / "scorer",
                output_root=tmp_path / "out",
                top_n=5,
                max_substitute_depth=0,
            )
    finally:
        blocker.release()


def test_run_daily_passes_target_length_8000(tmp_path: Path) -> None:
    """Regression: v0.3.0/0.3.1 hardcoded target_length=12000 in _run_daily_unlocked,
    but the pipeline's ±20% length tolerance window (9600-14400) is too narrow for
    real LLM output (~5000-12000 chars per the v0.3.1 e2e diagnostic run). Real
    LLM routinely produces bodies below 9600, failing the length gate → 0/5
    succeeded rate.

    Match v0.1.0/v0.2.0 e2e setting (target_length=8000) which is the only
    known-good value the heuristic was actually validated against (the v0.1.0
    hand-picked hook fixture pre-satisfied all 4 gates; the heuristic was
    never re-validated for open-ended hooks at 12000).
    """
    scorer = tmp_path / "scorer"
    _write_topic_scorer_output(scorer, n=12)
    out_root = tmp_path / "out"

    with patch("fanqie_short_story.daily.generate_story") as mock_gen:
        mock_gen.return_value = Path("output/stories/foo")
        run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=out_root,
            top_n=2,
            max_substitute_depth=0,
        )

    assert mock_gen.call_count == 2
    for call in mock_gen.call_args_list:
        assert call.kwargs["target_length"] == 8000, (
            f"expected target_length=8000 (matches v0.1.0 e2e setting), "
            f"got {call.kwargs['target_length']!r}. The previous 12000 "
            f"±20% window (9600-14400) is too narrow for real LLM output."
        )


def test_run_daily_records_api_calls_total(tmp_path: Path) -> None:
    """Spec §8 item 16: result.api_calls sums the per-story llm_calls across
    all 5 generated stories. Build fake story manifest.json files and verify
    the sum is computed from disk (via _read_manifest_llm_calls)."""
    scorer = tmp_path / "scorer"
    _write_topic_scorer_output(scorer, n=12)
    out_root = tmp_path / "out"
    today = datetime.now().date().isoformat()
    stories_dir = out_root / today / "stories"
    stories_dir.mkdir(parents=True)
    fake_paths = []
    for i in range(5):
        slug_dir = stories_dir / f"slug-{i}"
        slug_dir.mkdir()
        (slug_dir / "manifest.json").write_text(
            json.dumps({"llm_calls": 7 + i}), encoding="utf-8",
        )
        fake_paths.append(slug_dir)

    with patch(
        "fanqie_short_story.daily.generate_story", side_effect=fake_paths,
    ):
        result = run_daily(
            config=_make_config(tmp_path),
            scorer_root=scorer,
            output_root=out_root,
            top_n=5,
            max_substitute_depth=0,
        )

    assert len(result.generated) == 5
    assert result.api_calls == sum(7 + i for i in range(5))  # 7+8+9+10+11 = 45


# --------------------------------------------------------------------------
# Tests for write_daily_manifest — Task 8 / v0.3.0
# --------------------------------------------------------------------------


def test_write_daily_manifest_json_schema(tmp_path: Path) -> None:
    """Round-trip: write manifest, load JSON, validate required fields."""
    csv_path = tmp_path / "scores.csv"
    csv_path.write_text("rank,book_id\n", encoding="utf-8")
    result = DailyRunResult(
        date="2026-07-16",
        source_csv=csv_path,
        generated=[Path("output/stories/凡骨-壹")],
        failures=[{"rank": 7, "title": "x", "reason": "fail", "traceback_excerpt": None}],
        api_calls=27,
    )
    out_dir = tmp_path / "manifests"
    out_dir.mkdir()
    manifest_path = write_daily_manifest(out_dir, result)
    assert manifest_path == out_dir / "daily_manifest.json"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_scorer_root = str(csv_path.parent.parent.parent.parent)
    assert data["date"] == "2026-07-16"
    assert data["source_csv"] == str(csv_path)
    assert data["scorer_root"] == expected_scorer_root
    assert data["source_csv_mtime"] and "T" in data["source_csv_mtime"]
    assert data["top_n_requested"] == 5
    assert data["substitute_pool_size"] == 7
    assert len(data["generated"]) == 1
    assert data["generated"][0]["rank"] is None
    assert data["generated"][0]["title"] is None
    assert data["generated"][0]["author"] is None
    assert data["failures"] == result.failures
    assert data["totals"]["api_calls"] == 27


def test_write_daily_manifest_includes_source_csv_week(tmp_path: Path) -> None:
    """source_csv_week extracted from parent dir name (e.g., 2026-W29)."""
    csv_dir = tmp_path / "output" / "runs" / "2026-W29"
    csv_dir.mkdir(parents=True)
    csv_path = csv_dir / "scores.csv"
    csv_path.write_text("rank,book_id\n", encoding="utf-8")
    result = DailyRunResult(
        date="2026-07-16",
        source_csv=csv_path,
        generated=[],
        failures=[],
        api_calls=0,
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    manifest_path = write_daily_manifest(out_dir, result)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["source_csv_week"] == "2026-W29"


def test_write_daily_manifest_source_csv_week_fallback(tmp_path: Path) -> None:
    """No week pattern in parent dir name → 'unknown'."""
    csv_dir = tmp_path / "random" / "path"
    csv_dir.mkdir(parents=True)
    csv_path = csv_dir / "scores.csv"
    csv_path.write_text("rank,book_id\n", encoding="utf-8")
    result = DailyRunResult(
        date="2026-07-16",
        source_csv=csv_path,
        generated=[],
        failures=[],
        api_calls=0,
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    manifest_path = write_daily_manifest(out_dir, result)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["source_csv_week"] == "unknown"


# --------------------------------------------------------------------------
# Genre-mapping translation (v0.3.1 regression — the e2e test caught this
# against the real scorer, whose CSV uses fine-grained sub-genres like
# `xuanhuan-xiuzhen` while fanqie-short-story's pipeline only knows the
# 5 umbrella genres. The `batch` CLI handles this with
# `config.genre_mapping.get(source_genre, source_genre)`; the `daily`
# orchestrator must do the same.
# --------------------------------------------------------------------------


def test_run_daily_translates_csv_genre_via_config_mapping(tmp_path: Path) -> None:
    """run_daily must apply config.genre_mapping before calling generate_story.

    Regression: v0.3.0 daily pass book.genre straight through, which fails
    with `ValueError: Unknown genre: 'xuanhuan-xiuzhen'` against the real
    scorer output (the e2e test surfaced this). The `batch` CLI has been
    doing this translation since v0.1.0; `daily` must match.
    """
    scorer = tmp_path / "scorer"
    runs = scorer / "output" / "runs" / "2026-W30"
    runs.mkdir(parents=True)
    csv_path = runs / "scores.csv"
    csv_path.write_text(
        "rank,book_id,title,author,genre,chapters_count,in_read,overall,"
        "dim_hook,dim_plot,rationale\n"
        "1,id1,Title,Auth,xuanhuan-xiuzhen,100,1,8.0,7,7,r\n"
        "2,id2,T2,A2,kehuan-moshi,100,1,7.5,7,7,r\n"
        "3,id3,T3,A3,chuanqi,100,1,7.0,7,7,r\n",  # already-umbrella → no-op mapping
        encoding="utf-8",
    )
    # Populate the synopsis lookup so the orchestrator has real hooks.
    db = scorer / "output" / "fanqie.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("CREATE TABLE books (book_id TEXT PRIMARY KEY, synopsis TEXT)")
        conn.executemany(
            "INSERT INTO books VALUES (?, ?)",
            [("id1", "syn1"), ("id2", "syn2"), ("id3", "syn3")],
        )

    cfg = MagicMock()
    cfg.critique = MagicMock()
    cfg.genre_mapping = {
        "xuanhuan-xiuzhen": "chuanqi",
        "kehuan-moshi": "naodong",
        "chuanqi": "chuanqi",  # identity-mapping also passes through
    }

    with patch("fanqie_short_story.daily.generate_story") as mock_gen:
        mock_gen.return_value = Path("output/stories/x")
        result = run_daily(
            config=cfg,
            scorer_root=scorer,
            output_root=tmp_path / "out",
            top_n=3,
            max_substitute_depth=0,
        )

    assert result.failures == [], (
        f"expected no failures, got: {result.failures}"
    )
    assert mock_gen.call_count == 3
    # Every generate_story call must receive the MAPPED umbrella genre,
    # never the fine-grained CSV label.
    for call in mock_gen.call_args_list:
        passed_genre = call.kwargs["genre"]
        assert passed_genre in {"chuanqi", "naodong"}, (
            f"expected umbrella genre after mapping, got {passed_genre!r}"
        )
        assert "-" not in passed_genre, (
            f"fine-grained CSV genre leaked through to generate_story: "
            f"{passed_genre!r}"
        )


# --------------------------------------------------------------------------
# Default-config completeness: every chart in fanqie-topic-scorer's defaults
# must be translated by the default `genre_mapping`. Regression: v0.3.1's
# initial hand-curated mapping had `dushi-rich` (typo) instead of
# `dushi-richang`, and missed 7 of the 10 fanqie-topic-scorer sub-genres
# entirely — the live e2e test caught 3 of them with `Unknown genre`.
# --------------------------------------------------------------------------


def test_default_genre_mapping_covers_all_topic_scorer_subgenres() -> None:
    """Every `genre` label in fanqie-topic-scorer/config/defaults.yaml must
    appear as a KEY in fanqie-short-story/config/defaults.yaml's
    `genre_mapping`, with a value that is one of fanqie-short-story's 5
    umbrella genres.

    This stops typos (dushi-rich vs dushi-richang) and missing entries from
    shipping silently. If you add a new chart to the scorer's defaults,
    this test will fail until you add the matching umbrella mapping.
    """
    import yaml
    from fanqie_short_story import config as fss_config_mod

    # Resolve both YAMLs by going through the same path the runtime uses.
    repo_root = Path(fss_config_mod.__file__).resolve().parents[2]
    fss_yaml = repo_root / "config" / "defaults.yaml"
    scorer_yaml = (
        Path.home() / "CascadeProjects" / "projects" / "fanqie-topic-scorer"
        / "config" / "defaults.yaml"
    )
    assert fss_yaml.exists(), f"missing fanqie-short-story config at {fss_yaml}"
    assert scorer_yaml.exists(), (
        f"missing fanqie-topic-scorer config at {scorer_yaml}; "
        f"sibling repo not cloned to the conventional path"
    )

    with fss_yaml.open(encoding="utf-8") as f:
        fss_raw = yaml.safe_load(f) or {}
    with scorer_yaml.open(encoding="utf-8") as f:
        scorer_raw = yaml.safe_load(f) or {}

    # Authoritative source: the scorer's `fetch.charts[].genre` list.
    charts = (scorer_raw.get("fetch") or {}).get("charts") or []
    scorer_subgenres = sorted({c["genre"] for c in charts if "genre" in c})

    mapping = fss_raw.get("genre_mapping") or {}
    UMBRELLA = {"chuanqi", "xianyan", "xuanyi", "tianchong", "naodong"}

    missing = [g for g in scorer_subgenres if g not in mapping]
    invalid_values = sorted(
        {g: mapping[g] for g in scorer_subgenres if g in mapping}.items()
        - {kv for kv in mapping.items() if kv[1] in UMBRELLA}
    )
    assert not missing, (
        f"genre_mapping is missing entries for these scorer sub-genres: "
        f"{missing}. Add them to config/defaults.yaml so that `daily run-once` "
        f"stops failing with `Unknown genre` against the real scorer."
    )
    assert not invalid_values, (
        f"genre_mapping maps scorer sub-genres to non-umbrella genres "
        f"(must be one of {sorted(UMBRELLA)}): {invalid_values}"
    )
