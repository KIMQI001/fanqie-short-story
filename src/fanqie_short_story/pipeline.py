"""Top-level pipeline: hook + genre + length → story directory with all artifacts.

v0.4.0 EXTENDS v0.2.0 with:
  * Outline regeneration on structural-severity editor-critic failure
    (capped by config.critique.editor_max_structural_failures, default 1)
  * De-AI-flavor polish.run() applied AFTER body passes the editor critic
  * memory_object detection (first strong-object match in body)
  * New manifest fields: schema_version, mood_axis, memory_object,
    polish_applied, polish_intensity, polish_ai_odor_score,
    polish_rules_applied, outline_backtrack_count, editor_categories_passed

The v0.2.0 llm_critique (5-flat-dimension narrative review) is replaced by
llm_editor_critique (5-category editor perspective) in v0.4.0. The legacy
function stays in llm_critique.py for backward compat but is no longer
called from the pipeline.

Methodology source: tianyayu6/fanqie-hit-short-story methodology.md
(MIT, 2026-06-17), the 番茄爆款 short-story pipeline.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fanqie_short_story.body import Body, generate_body
from fanqie_short_story.config import Config
from fanqie_short_story.cover import generate_cover
from fanqie_short_story.critique import heuristic_critique
from fanqie_short_story.llm_critique import (
    EditorReport,
    _EDITOR_CATEGORIES,
    llm_editor_critique,
)
from fanqie_short_story.manifest import StoryManifest, write_manifest
from fanqie_short_story.outline import generate_outline
from fanqie_short_story.polish import PolishResult, run as run_polish
from fanqie_short_story.synopsis import generate_synopsis
from fanqie_short_story.title import generate_titles


# v0.4.0 schema version stamped onto every manifest.
SCHEMA_VERSION = "0.4.0"

# Strong memory objects per the tomato methodology. Pipeline scans body
# text and reports the FIRST occurrence so audit logs surface the
# concrete 物件 that anchored the story's truth-reveal.
_MEMORY_OBJECTS: tuple[str, ...] = (
    "录像带", "婚书", "病历", "亲子鉴定", "倒计时", "账本",
    "弹幕截图", "外卖单", "快递单", "旧照片", "转账记录", "遗诏", "玉佩",
)


class GenerationFailed(Exception):
    def __init__(self, msg: str, output_dir: Path):
        super().__init__(msg)
        self.output_dir = output_dir


def _slugify(hook: str, max_len: int = 30) -> str:
    s = re.sub(r"[^一-鿿A-Za-z0-9]+", "-", hook)
    s = s.strip("-").lower()
    return s[:max_len] or "story"


def _detect_memory_object(body_text: str) -> str | None:
    """Return the first strong memory object in body_text, or None.

    Methodology source: tianyayu6/fanqie-hit-short-story methodology.md
    "梗与题材 — 至少 1 个记忆物件" rule. Order in _MEMORY_OBJECTS drives
    which object wins ties; we keep a fixed lookup so test assertions are
    deterministic."""
    for obj in _MEMORY_OBJECTS:
        if obj in body_text:
            return obj
    return None


def _editor_categories_to_dict(report: EditorReport) -> dict[str, bool]:
    """Flatten EditorReport.categories into a {name: passed} dict for the manifest."""
    return {c.name: bool(c.passed) for c in report.categories}


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

    # v0.4.0 polish config resolution (defaults from config.polish, fall back
    # to intensity=1 rule-based if block missing).
    polish_enabled = bool(config.polish.get("enabled", True))
    polish_default_intensity = int(config.polish.get("default_intensity", 1))
    polish_auto_bump = bool(config.polish.get("auto_bump_on_backtrack", True))
    editor_backtrack_cap = int(
        config.critique.get("editor_max_structural_failures", 1)
    )

    # 1. Outline — regenerated on structural-failure backtrack
    outline = generate_outline(
        hook=hook, genre=genre, target_length=target_length,
        tone=tone or "sweet_with_suspense", config=config,
    )
    (story_dir / "outline.md").write_text(
        outline.to_prompt_string(), encoding="utf-8",
    )

    # 2. Body — heuristic → LLM editor critic chain with outline-backtrack
    body: Body | None = None
    feedback: list[str] | None = None
    iterations = 0
    last_editor_report: EditorReport | None = None

    # Counters used both for loop bookkeeping and the success-path manifest.
    heuristic_attempts = 0
    llm_critic_attempts = 0
    outline_backtrack_count = 0
    accepted_after_critic_cap = False
    critique_strategy = "heuristic_only"   # upgraded to "heuristic_then_editor" if editor runs
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
            length_tolerance=config.critique.get("length_tolerance", 0.50),
        )
        heuristic_attempts += 1
        if not h_report.passed:
            feedback = h_report.notes
            critique_notes.append(f"[heuristic] {'; '.join(h_report.notes)}")
            continue

        if not llm_enabled:
            # heuristic-only mode (kill switch)
            break

        if llm_critic_attempts >= max_llm_calls:
            # Cap reached BEFORE another call — accept body with the latest critic's failure.
            print("warning: LLM editor critic cap reached; accepting body")
            accepted_after_critic_cap = True
            critique_strategy = "heuristic_then_editor"
            break

        editor_report = llm_editor_critique(
            body, hook, genre, target_length, config=config,
        )
        llm_critic_attempts += 1
        last_editor_report = editor_report

        if editor_report.all_passed:
            critique_strategy = "heuristic_then_editor"
            break

        # Build feedback notes for retry / backtrack.
        failed_notes = [
            f"[{c.name}] {c.notes}" for c in editor_report.categories if not c.passed
        ]
        feedback = failed_notes
        critique_notes.append(f"[editor_critic] {'; '.join(failed_notes)}")

        # v0.4.0 outline backtrack: structural failure + cap not exhausted
        # → regenerate outline + body. Surface failures alone don't backtrack
        # but still retry body (with failed-category notes as feedback).
        if editor_report.structural_failure:
            critique_strategy = "heuristic_then_editor"
            if outline_backtrack_count < editor_backtrack_cap:
                outline_backtrack_count += 1
                outline = generate_outline(
                    hook=hook, genre=genre, target_length=target_length,
                    tone=tone or "sweet_with_suspense", config=config,
                )
                (story_dir / "outline.md").write_text(
                    outline.to_prompt_string(), encoding="utf-8",
                )
                critique_notes.append(
                    f"[outline_backtrack] regenerated outline "
                    f"({outline_backtrack_count}/{editor_backtrack_cap})"
                )
                feedback = failed_notes
                continue
            # Backtrack cap exhausted — accept body with structural failure.
            accepted_after_critic_cap = True
            print(
                f"warning: editor structural-failure cap reached "
                f"({outline_backtrack_count}/{editor_backtrack_cap}); "
                f"accepting body"
            )
            break

        # Surface-only failure: retry body WITHOUT outline backtrack.
        critique_strategy = "heuristic_then_editor"
        continue
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

    # 2b. Polish — runs AFTER body passes (or is accepted by cap).
    polish_applied = False
    polish_intensity = 0
    polish_ai_odor_score = 0.0
    polish_rules_applied: list[str] = []

    if polish_enabled and body is not None:
        polish_intensity = polish_default_intensity
        if outline_backtrack_count > 0 and polish_auto_bump:
            polish_intensity = min(3, polish_intensity + 1)
        polished: PolishResult = run_polish(
            body.text, intensity=polish_intensity, config=config,
        )
        polish_applied = True
        polish_intensity = polished.intensity
        polish_ai_odor_score = polished.ai_odor_score
        polish_rules_applied = list(polished.rules_applied)
        body = Body.from_text(polished.text)

    if body is not None:
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

    # 5. Manifest — v0.4.0 schema with new fields.
    body_text_for_audit = body.text if body is not None else ""
    memory_object = _detect_memory_object(body_text_for_audit)
    editor_categories_passed = (
        _editor_categories_to_dict(last_editor_report)
        if last_editor_report is not None else {}
    )

    manifest = StoryManifest(
        slug=slug,
        hook=hook,
        genre=genre,
        target_length=target_length,
        actual_length=body.char_count if body is not None else 0,
        tone=tone,
        model=config.model,
        created_at=datetime.now(timezone.utc),
        critique_iterations=iterations,
        critique_notes=critique_notes,
        critique_strategy=critique_strategy,
        heuristic_attempts=heuristic_attempts,
        llm_critic_attempts=llm_critic_attempts,
        accepted_after_critic_cap=accepted_after_critic_cap,
        cover_backend=cover_backend_used,
        # outline (1) + body attempts (iterations) + title (1) + synopsis (1).
        # Does NOT include LLM critic calls — those are tracked separately in llm_critic_attempts.
        llm_calls=1 + iterations + 1 + 1,
        estimated_tokens=None,
        output_files=sorted(
            p.name for p in story_dir.iterdir()
            if p.is_file() and p.name != "manifest.json"
        ),
        schema_version=SCHEMA_VERSION,
        mood_axis=outline.mood_axis,
        memory_object=memory_object,
        polish_applied=polish_applied,
        polish_intensity=polish_intensity,
        polish_ai_odor_score=polish_ai_odor_score,
        polish_rules_applied=polish_rules_applied,
        outline_backtrack_count=outline_backtrack_count,
        editor_categories_passed=editor_categories_passed,
    )
    write_manifest(story_dir, manifest)

    return story_dir