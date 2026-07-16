"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from fanqie_short_story.config import Config


@pytest.fixture
def fake_config() -> Config:
    return Config(
        model="MiniMax-M2.7",
        api_base="https://api.minimaxi.com/anthropic",
        api_key="sk-test",
        max_retries=3,
        critique={
            "length_tolerance": 0.20,
            "hook_window_chars": 200,
            "ending_window_chars": 500,
            "max_pov_switches": 3,
        },
        body={"default_temperature": 0.7, "default_max_tokens": 20000},
        outline={"default_temperature": 0.6, "default_max_tokens": 2000},
        title={"candidate_count": 5},
        synopsis={"target_length_chars": 120},
        cover={"default_backend": "auto", "image_size": [600, 800]},
        genre_mapping={"kehuan-moshi": "naodong"},
    )
