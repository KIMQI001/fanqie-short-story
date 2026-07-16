"""YAML + env config loader. Mirrors fanqie-topic-scorer's config pattern."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    model: str
    api_base: str
    api_key: str
    max_retries: int
    critique: dict[str, Any]
    body: dict[str, Any]
    outline: dict[str, Any]
    title: dict[str, Any]
    synopsis: dict[str, Any]
    cover: dict[str, Any]
    genre_mapping: dict[str, str]
    daily: dict[str, Any] = field(default_factory=dict)


def load_config(yaml_path: Path | str) -> Config:
    """Load config from YAML + env. Fail-fast on missing API key."""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise ConfigError(f"Config file not found: {yaml_path}")

    with yaml_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ConfigError(
            "MINIMAX_API_KEY not set in env. "
            "Export it before running fanqie-story: "
            "`export MINIMAX_API_KEY=sk-cp-...`"
        )

    return Config(
        model=os.environ.get("FANQIE_STORY_MODEL", raw.get("model", "MiniMax-M2.7")),
        api_base=os.environ.get("FANQIE_STORY_API_BASE",
                                raw.get("api_base", "")),
        api_key=api_key,
        max_retries=int(raw.get("max_retries", 3)),
        critique=raw.get("critique", {}),
        body=raw.get("body", {}),
        outline=raw.get("outline", {}),
        title=raw.get("title", {}),
        synopsis=raw.get("synopsis", {}),
        cover=raw.get("cover", {}),
        genre_mapping=raw.get("genre_mapping", {}),
        daily=raw.get("daily", {}),
    )
