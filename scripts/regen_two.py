"""Regen 2 covers with hand-picked titles from titles.txt."""
import json
import sys
import time
from pathlib import Path

from fanqie_short_story.cover import generate_cover

ROOT = Path("/Users/troah/CascadeProjects/projects/fanqie-short-story")
STORIES = ROOT / "output/daily/2026-07-18/stories"
TARGETS = ["修仙闲逛-游历终-颈鹿", "末存案供商-板王仔"]

started = time.monotonic()
for slug in TARGETS:
    story_dir = STORIES / slug
    title_path = story_dir / "titles.txt"
    title = title_path.read_text(encoding="utf-8").strip().split("\n")[0]
    story_manifest = json.loads((story_dir / "manifest.json").read_text(encoding="utf-8"))
    hook = story_manifest["hook"]
    genre = story_manifest["genre"]
    print(f"{slug}: title={title!r} genre={genre}")
    backend = generate_cover(
        slug=slug, hook=hook, genre=genre,
        title=title,
        output_dir=STORIES,
    )
    sz = (story_dir / "cover.jpg").stat().st_size
    print(f"  ok ({sz} bytes, backend={backend})")
print(f"done in {int(time.monotonic() - started)}s")
