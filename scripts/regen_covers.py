"""Regenerate covers for the 5 stories in output/daily/2026-07-18/.

Cover title priority (matches pipeline.generate_story):
  1. titles.txt first non-empty line  (LLM-generated — usually smooth)
  2. book.title from daily_manifest    (raw fanqie — often awkward)
  3. hook[:60]                         (last-resort truncation)

Reads MINIMAX_API_KEY from env to fill missing titles.txt for stories where
the LLM flaked on the original run (v0.3.4 known issue).

Usage:  python scripts/regen_covers.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from fanqie_short_story.body import Body
from fanqie_short_story.config import load_config
from fanqie_short_story.cover import generate_cover
from fanqie_short_story.title import generate_titles

ROOT = Path(__file__).resolve().parents[1]
DAILY_DIR = ROOT / "output" / "daily" / "2026-07-18"
MANIFEST_PATH = DAILY_DIR / "daily_manifest.json"


def _first_title_from_file(titles_path: Path) -> str | None:
    if not titles_path.exists():
        return None
    for line in titles_path.read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("0123456789.、) ")
        if line:
            return line
    return None


def _fill_missing_titles(stories_dir: Path, entries: list[dict], config) -> int:
    """For each story with empty titles.txt, re-run generate_titles() and
    write back the result. Returns count filled."""
    filled = 0
    for entry in entries:
        slug = entry["slug"]
        story_dir = stories_dir / slug
        titles_path = story_dir / "titles.txt"
        existing = _first_title_from_file(titles_path)
        if existing:
            continue
        body_path = story_dir / "body.txt"
        if not body_path.exists():
            print(f"  [{slug}] SKIP: no body.txt")
            continue
        body = Body.from_text(body_path.read_text(encoding="utf-8"))
        manifest = json.loads((story_dir / "manifest.json").read_text(encoding="utf-8"))
        hook = manifest["hook"]
        genre = manifest["genre"]
        print(f"  [{slug}] filling titles.txt (was empty)...")
        titles = generate_titles(
            body, hook, genre,
            n=config.title.get("candidate_count", 5), config=config,
        )
        titles_path.write_text("\n".join(titles), encoding="utf-8")
        print(f"           → {len(titles)} titles, primary: {titles[0] if titles else '(none)'}")
        filled += 1
    return filled


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"missing: {MANIFEST_PATH}", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    stories_dir = DAILY_DIR / "stories"
    entries = manifest.get("generated", [])
    if not entries:
        print("no generated entries", file=sys.stderr)
        return 1

    config = load_config(ROOT / "config" / "defaults.yaml")
    print(f"step 1: fill missing titles.txt for stories that flaked...")
    filled = _fill_missing_titles(stories_dir, entries, config)
    print(f"  filled {filled} titles.txt files\n")

    print(f"step 2: regenerating covers for {len(entries)} stories...")
    started = time.monotonic()
    for i, entry in enumerate(entries, 1):
        slug = entry["slug"]
        book_title = entry["title"]
        story_dir = stories_dir / slug
        if not story_dir.exists():
            print(f"  [{i}/{len(entries)}] SKIP {slug}: dir missing")
            continue
        llm_title = _first_title_from_file(story_dir / "titles.txt")
        cover_title = llm_title or book_title
        story_manifest = json.loads((story_dir / "manifest.json").read_text(encoding="utf-8"))
        hook = story_manifest["hook"]
        genre = story_manifest["genre"]
        cover_path = story_dir / "cover.jpg"
        old_size = cover_path.stat().st_size if cover_path.exists() else 0
        source = "titles.txt" if llm_title else "book.title"
        print(f"  [{i}/{len(entries)}] {slug}")
        print(f"           title[{source}]: {cover_title!r}")
        backend = generate_cover(
            slug=slug, hook=hook, genre=genre,
            title=cover_title,
            output_dir=stories_dir,
        )
        new_size = cover_path.stat().st_size if cover_path.exists() else 0
        print(f"           ok ({old_size}→{new_size} bytes, backend={backend})")
    elapsed = int(time.monotonic() - started)
    print(f"\ndone in {elapsed}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
