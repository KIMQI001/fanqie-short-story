"""manifest.json writer — audit trail for one generated story."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class StoryManifest:
    slug: str
    hook: str
    genre: str
    target_length: int
    actual_length: int
    tone: str | None
    model: str
    created_at: datetime
    critique_iterations: int
    critique_notes: list[str]
    cover_backend: str | None
    llm_calls: int
    output_files: list[str]
    failed: bool = False
    failure_reason: str | None = None
    estimated_tokens: int | None = None

    critique_strategy: str = "heuristic_only"
    heuristic_attempts: int = 0
    llm_critic_attempts: int = 0
    accepted_after_critic_cap: bool = False

    # v0.4.0 additions — tomato methodology audit trail.
    schema_version: str = "0.4.0"
    mood_axis: tuple[str, str | None] | None = None
    memory_object: str | None = None
    polish_applied: bool = False
    polish_intensity: int = 0
    polish_ai_odor_score: float = 0.0
    polish_rules_applied: list[str] = field(default_factory=list)
    outline_backtrack_count: int = 0
    editor_categories_passed: dict[str, bool] = field(default_factory=dict)


def write_manifest(output_dir: Path, manifest: StoryManifest) -> Path:
    payload = asdict(manifest)
    # ISO-8601 with timezone preserved
    payload["created_at"] = manifest.created_at.isoformat()
    out = output_dir / "manifest.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out
