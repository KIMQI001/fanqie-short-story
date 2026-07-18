"""Cover generation: invoke the cover_gen CLI by generating a single-entry
books.yaml on the fly.

We don't reimplement cover logic — cover_gen (a sibling project at
`~/CascadeProjects/projects/book`) handles the AI-backend + typography +
manifest pipeline. v0.1.0 of cover_gen is a *batch* tool that reads
`books.yaml` and produces one cover per entry; it has no per-book flags.

So we:
  1. Write a single-entry books.yaml to a fresh tempdir.
  2. Translate the umbrella genre (chuanqi, xianyan, …) to cover_gen's
     4-genre taxonomy (xuanhuan, yanqing, mystery, other).
  3. Invoke `cover_gen generate --config <yaml> --project-root <book repo>
     --output-root <tempdir>/out --backend auto`.
  4. Harvest `<tempdir>/out/<slug>/draft/cover.png` (NOT top-level cover.jpg
     like the v0.3.3 wrapper assumed) and copy it to `<story_dir>/cover.jpg`.
  5. Read `backend` from cover_gen's `<tempdir>/out/<slug>/manifest.json`.

The tempdir is removed in a `finally` block so failures don't leak.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml


COVER_GEN_BIN = "cover_gen"  # must be on PATH; installed via `pip install -e ~/CascadeProjects/projects/book`
DEFAULT_BACKEND = "auto"
DEFAULT_AUTHOR = "我是btc大户"  # shown on every cover; was "fanqie-story" through v0.3.4

# Default project root for cover_gen (its `config/` and `genres/` dirs live here).
# Override by passing `cover_gen_project_root` to generate_cover().
_DEFAULT_COVER_GEN_PROJECT_ROOT = Path("/Users/troah/CascadeProjects/projects/book")

# Mapping: fanqie-short-story umbrella genre → cover_gen genre.
# Keep keys aligned with the 5-umbrella set in config/defaults.yaml.
_GENRE_MAP: dict[str, str] = {
    "chuanqi": "xuanhuan",      # 传奇 / 东方仙侠 / 传统玄幻 → 玄幻
    "xianyan": "yanqing",       # 现代言情 → 言情
    "xuanyi": "mystery",        # 悬疑 → 推理
    "tianchong": "yanqing",     # 甜宠 → 言情 (closest fit)
    "naodong": "other",         # 脑洞 (surreal/conceptual) → 杂项 (cover_gen template fallback)
}


def _map_genre(umbrella_genre: str) -> str:
    """Translate a fanqie-short-story umbrella genre to a cover_gen genre.
    Unknown / future genres fall back to "other" (cover_gen has an `other` template).
    """
    return _GENRE_MAP.get(umbrella_genre, "other")


class CoverError(Exception):
    """Raised when cover_gen subprocess fails or produces no cover image."""


def generate_cover(
    slug: str,
    hook: str,
    genre: str,
    output_dir: Path,
    *,
    title: str | None = None,
    author: str = DEFAULT_AUTHOR,
    backend: str = DEFAULT_BACKEND,
    timeout: int = 600,
    cover_gen_project_root: Path = _DEFAULT_COVER_GEN_PROJECT_ROOT,
) -> str:
    """Invoke `cover_gen generate` via a single-entry books.yaml to produce
    `<output_dir>/<slug>/cover.jpg`.

    `cover_gen_project_root` is the cover_gen repo (must contain `config/`
    and `genres/`). Defaults to the project's known install path; pass an
    explicit value to override in tests or other environments.

    `title` is what shows up on the cover. If None, falls back to the first
    60 chars of `hook` (the synopsis) — kept for backwards compat with
    callers that only have a hook in hand. Pass the original book title
    (e.g. `book.title`) for proper cover typography.

    `author` defaults to "我是btc大户" — the byline shown on every cover.

    Returns the backend used by cover_gen (parsed from its manifest).
    Raises CoverError on subprocess failure, missing cover_gen on PATH,
    or no cover image produced.
    """
    if shutil.which(COVER_GEN_BIN) is None:
        raise CoverError(
            f"{COVER_GEN_BIN} not on PATH. Install cover_gen: "
            f"pip install -e ~/CascadeProjects/projects/book"
        )

    output_dir = Path(output_dir)
    story_dir = output_dir / slug
    story_dir.mkdir(parents=True, exist_ok=True)

    # Wrap the whole subprocess + harvest in try/finally so the tempdir is
    # removed even if cover_gen crashes mid-flight.
    workdir = Path(tempfile.mkdtemp(prefix="fanqie_cover_"))
    try:
        books_yaml = workdir / "books.yaml"
        books_yaml.write_text(
            yaml.safe_dump(
                {
                    "books": [
                        {
                            "title": title if title else hook[:60],
                            "author": author,
                            "genre": _map_genre(genre),
                            "synopsis": hook[:200],
                            "output_name": slug,
                        }
                    ],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        out_root = workdir / "out"
        cmd = [
            COVER_GEN_BIN, "generate",
            "--config", str(books_yaml),
            "--project-root", str(cover_gen_project_root),
            "--output-root", str(out_root),
            "--backend", backend,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip().splitlines()
            tail = "\n".join(stderr[-10:])
            raise CoverError(
                f"cover_gen failed (rc={result.returncode}): {tail[:500]}"
            )

        # cover_gen writes: <out_root>/<slug>/draft/cover.png (+ raw.png, manifest.json)
        cover_src = out_root / slug / "draft" / "cover.png"
        if not cover_src.exists():
            # Widen search in case cover_gen changed its layout in a later version.
            candidates = list(out_root.rglob("cover.*"))
            if not candidates:
                raise CoverError(
                    f"cover_gen exited 0 but no cover image found under {out_root}"
                )
            cover_src = candidates[0]
        cover_dst = story_dir / "cover.jpg"
        shutil.copy(cover_src, cover_dst)

        # Best-effort: read backend from cover_gen's manifest.json.
        backend_used = backend
        for m in out_root.rglob("manifest.json"):
            try:
                data = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and "backend" in data:
                backend_used = data["backend"]
                break

        return backend_used
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
