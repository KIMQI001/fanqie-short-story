"""Tests for fanqie_short_story.daily — daily orchestrator."""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import pytest

from fanqie_short_story.daily import find_latest_scores_csv


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


import sqlite3

from fanqie_short_story.daily import (
    find_latest_scores_csv, load_top_n,  # add load_top_n to existing import
)


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