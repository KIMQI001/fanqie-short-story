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