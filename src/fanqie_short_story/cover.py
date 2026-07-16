"""Cover generation: subprocess call to the cover_gen CLI.

We don't reimplement cover logic — cover_gen already handles
minimax-primary / comfyui-fallback. We just invoke it as a black box.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


COVER_GEN_BIN = "cover_gen"  # must be on PATH; same as fanqie-story's own entry
DEFAULT_BACKEND = "auto"


class CoverError(Exception):
    """Raised when cover_gen subprocess fails or produces no cover image."""


def generate_cover(
    slug: str,
    hook: str,
    genre: str,
    output_dir: Path,
    *,
    backend: str = DEFAULT_BACKEND,
    timeout: int = 600,
) -> str:
    """Invoke `cover_gen generate` to produce <output_dir>/<slug>/cover.jpg.

    Returns the backend that was used (parsed from cover_gen's manifest).
    Raises CoverError on subprocess failure or missing cover file.
    """
    if shutil.which(COVER_GEN_BIN) is None:
        raise CoverError(
            f"{COVER_GEN_BIN} not on PATH. Install cover_gen: "
            f"pip install -e ~/CascadeProjects/projects/book"
        )

    story_dir = output_dir / slug
    story_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        COVER_GEN_BIN, "generate",
        "--book-id", slug,
        "--genre", genre,
        "--backend", backend,
        "--output-root", str(output_dir),
        "--title", hook[:30],
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise CoverError(
            f"cover_gen failed (rc={result.returncode}): {result.stderr[:500]}"
        )

    cover_path = story_dir / "cover.jpg"
    if not cover_path.exists():
        # cover_gen may write to <output_root>/<book-id>/cover.jpg or similar;
        # search for any cover image under output_dir.
        candidates = list(output_dir.rglob("cover.*"))
        if not candidates:
            raise CoverError(
                f"cover_gen exited 0 but no cover image found under {output_dir}"
            )
        # Pick the first candidate matching our slug.
        for c in candidates:
            if slug in str(c):
                shutil.copy(c, cover_path)
                break
        else:
            shutil.copy(candidates[0], cover_path)

    # Try to read backend from the manifest cover_gen wrote.
    manifest_candidates = list(output_dir.rglob("manifest.json"))
    backend_used = backend
    for m in manifest_candidates:
        if slug not in str(m):
            continue
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
            if "backend" in data:
                backend_used = data["backend"]
                break
        except (OSError, json.JSONDecodeError):
            pass

    return backend_used
