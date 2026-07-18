"""Top-level pipeline: hook + genre + length → story directory with all artifacts."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fanqie_short_story.body import Body, generate_body
from fanqie_short_story.config import Config
from fanqie_short_story.cover import generate_cover
from fanqie_short_story.critique import heuristic_critique
from fanqie_short_story.llm_critique import llm_critique
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
    title: str | None = None,
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

    # 2. Body — heuristic → LLM critic chain with retry loop
    body: Body | None = None
    feedback: list[str] | None = None
    iterations = 0

    # Counters used both for loop bookkeeping and the success-path manifest.
    heuristic_attempts = 0
    llm_critic_attempts = 0
    accepted_after_critic_cap = False
    critique_strategy = "heuristic_only"   # upgraded to "heuristic_then_llm" if the LLM critic runs
    critique_notes: list[str] = []

    # NOTE: max_retries stays at top-level config (v0.1.0 contract — NOT under critique:).
    max_retries = config.max_retries
    max_llm_calls = config.critique.get("llm_max_calls_per_story", 3)
    llm_enabled = config.critique.get("llm_enabled", True)

    while iterations <= max_retries:
        iterations += 1   # count each body generation attempt (preserves v0.1.0 semantics)
        body = generate_body(
            outline, hook, genre, target_length,
            tone=tone or "sweet_with_suspense",
            critique_feedback=feedback, config=config,
        )

        h_report = heuristic_critique(
            body, hook, target_length,
            length_tolerance=config.critique.get("length_tolerance", 0.20),
        )
        heuristic_attempts += 1
        if not h_report.passed:
            feedback = h_report.notes
            critique_notes.append(f"[heuristic] {'; '.join(h_report.notes)}")
            continue

        if not llm_enabled:
            # heuristic-only mode (v0.1.0 behavior with kill switch)
            break

        if llm_critic_attempts >= max_llm_calls:
            # Cap reached BEFORE another call — accept body with the latest critic's failure.
            print("warning: LLM critic cap reached; accepting body")
            accepted_after_critic_cap = True
            critique_strategy = "heuristic_then_llm"
            break

        llm_report = llm_critique(
            body, hook, genre, target_length, config=config,
        )
        llm_critic_attempts += 1
        if llm_report.passed:
            critique_strategy = "heuristic_then_llm"
            break

        feedback = [llm_report.notes]   # WRAP: body expects list[str]
        critique_notes.append(f"[llm_critic] {llm_report.notes}")
    else:
        # Loop exhausted without break. Preserve v0.1.0's _failed/ artifact writes for audit.
        failed_dir = story_dir / "_failed"
        failed_dir.mkdir(exist_ok=True)
        if body is not None:
            (failed_dir / "body.txt").write_text(body.text, encoding="utf-8")
        (failed_dir / "critique.txt").write_text(
            "\n".join(critique_notes), encoding="utf-8",
        )
        raise GenerationFailed(
            f"critique loop exhausted after {iterations} attempts",
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

    # Cover title priority: LLM-generated title (from titles.txt) > first
    # non-blank line of body.txt (chapter heading) > caller-supplied title.
    # The caller-supplied title is usually a raw fanqie book.title — a *seed*
    # for scoring/genre matching, NOT the title of our generated novel. We
    # never want that on the cover of our own output. Fall back to a chapter
    # heading or body[:30] if the LLM title generator flaked.
    cover_title = None
    for line in (story_dir / "titles.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("0123456789.、) ")
        if line:
            cover_title = line
            break
    if cover_title is None:
        # Try the first non-blank, non-# line of body.txt.
        for line in (story_dir / "body.txt").read_text(encoding="utf-8").splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                cover_title = line[:30].rstrip(",。;:!?、")
                break
    if cover_title is None:
        cover_title = title  # absolute last resort; caller knows best

    # 4. Cover — best-effort; failure does NOT block the rest
    cover_backend_used: str | None = None
    try:
        cover_backend_used = generate_cover(
            slug=slug, hook=hook, genre=genre,
            title=cover_title,
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
        critique_notes=critique_notes,  # v0.2.0: accumulated per-stage critique notes
        critique_strategy=critique_strategy,
        heuristic_attempts=heuristic_attempts,
        llm_critic_attempts=llm_critic_attempts,
        accepted_after_critic_cap=accepted_after_critic_cap,
        cover_backend=cover_backend_used,
        # outline (1) + body attempts (iterations) + title (1) + synopsis (1).
        # Does NOT include LLM critic calls — those are tracked separately in llm_critic_attempts.
        llm_calls=1 + iterations + 1 + 1,
        estimated_tokens=None,  # not tracked yet; reserved field for future token accounting
        output_files=sorted(
            p.name for p in story_dir.iterdir()
            if p.is_file() and p.name != "manifest.json"
        ),
    )
    write_manifest(story_dir, manifest)

    return story_dir
