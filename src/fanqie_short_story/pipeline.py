"""Top-level pipeline: hook + genre + length → story directory with all artifacts."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fanqie_short_story.body import Body, generate_body
from fanqie_short_story.config import Config
from fanqie_short_story.cover import generate_cover
from fanqie_short_story.critique import critique
from fanqie_short_story.manifest import StoryManifest, write_manifest
from fanqie_short_story.outline import generate_outline
from fanqie_short_story.synopsis import generate_synopsis
from fanqie_short_story.title import generate_titles


class GenerationFailed(Exception):
    def __init__(self, msg: str, output_dir: Path):
        super().__init__(msg)
        self.output_dir = output_dir


def _slugify(hook: str, max_len: int = 30) -> str:
    s = re.sub(r"[^一-鿿A-Za-z0-9]+", "-", hook)
    s = s.strip("-").lower()
    return s[:max_len] or "story"


def generate_story(
    *,
    hook: str,
    genre: str,
    target_length: int,
    tone: str | None = None,
    output_dir: Path | None = None,
    slug: str | None = None,
    config: Config,
    cover_backend: str = "auto",
) -> Path:
    if output_dir is None:
        output_dir = Path("output/stories")
    output_dir = Path(output_dir)
    if slug is None:
        slug = _slugify(hook)
    story_dir = output_dir / slug
    if story_dir.exists() and any(story_dir.iterdir()):
        raise FileExistsError(
            f"{story_dir} is not empty. Pass a different --output-dir or --slug, "
            f"or remove the directory first."
        )
    story_dir.mkdir(parents=True, exist_ok=True)

    # 1. Outline
    outline = generate_outline(
        hook=hook, genre=genre, target_length=target_length,
        tone=tone or "sweet_with_suspense", config=config,
    )
    (story_dir / "outline.md").write_text(
        outline.to_prompt_string(), encoding="utf-8",
    )

    # 2. Body — with critique-and-retry loop
    max_retries = config.max_retries
    body: Body | None = None
    feedback: list[str] | None = None
    iterations = 0
    while iterations <= max_retries:
        body = generate_body(
            outline, hook, genre, target_length,
            tone=tone or "sweet_with_suspense",
            critique_feedback=feedback, config=config,
        )
        iterations += 1
        report = critique(
            body, hook, target_length,
            length_tolerance=config.critique.get("length_tolerance", 0.20),
        )
        if report.passed:
            break
        feedback = report.notes
    else:
        # Loop exited without `break`: critique kept failing.
        failed_dir = story_dir / "_failed"
        failed_dir.mkdir(exist_ok=True)
        if body is not None:
            (failed_dir / "body.txt").write_text(body.text, encoding="utf-8")
        (failed_dir / "critique.txt").write_text(
            "\n".join(report.notes), encoding="utf-8",
        )
        raise GenerationFailed(
            f"critique failed after {iterations} attempts: {report.failed_gates}",
            story_dir,
        )

    (story_dir / "body.txt").write_text(body.text, encoding="utf-8")

    # 3. Title + synopsis
    titles = generate_titles(
        body, hook, genre,
        n=config.title.get("candidate_count", 5), config=config,
    )
    (story_dir / "titles.txt").write_text(
        "\n".join(titles), encoding="utf-8",
    )

    synopsis = generate_synopsis(
        body, hook, genre,
        n=config.synopsis.get("target_length_chars", 120), config=config,
    )
    (story_dir / "synopsis.md").write_text(
        f"# 简介\n\n{synopsis}\n", encoding="utf-8",
    )

    # 4. Cover — best-effort; failure does NOT block the rest
    cover_backend_used: str | None = None
    try:
        cover_backend_used = generate_cover(
            slug=slug, hook=hook, genre=genre,
            output_dir=output_dir, backend=cover_backend,
        )
    except Exception as e:
        # Pipeline continues; manifest records cover_backend=None.
        print(f"warning: cover generation failed: {e}")

    # 5. Manifest
    manifest = StoryManifest(
        slug=slug,
        hook=hook,
        genre=genre,
        target_length=target_length,
        actual_length=body.char_count,
        tone=tone,
        model=config.model,
        created_at=datetime.now(timezone.utc),
        critique_iterations=iterations,
        critique_notes=report.notes,
        cover_backend=cover_backend_used,
        llm_calls=1 + iterations + 1 + 1,  # outline + body attempts + title + synopsis
        estimated_tokens=0,  # tracked separately in future
        output_files=sorted(
            p.name for p in story_dir.iterdir()
            if p.is_file() and p.name != "manifest.json"
        ),
    )
    write_manifest(story_dir, manifest)

    return story_dir
