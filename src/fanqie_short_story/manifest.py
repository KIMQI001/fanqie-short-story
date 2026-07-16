"""manifest.json writer — audit trail for one generated story."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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
    estimated_tokens: int
    output_files: list[str]
    failed: bool = False
    failure_reason: str | None = None


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
