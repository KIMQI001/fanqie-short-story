"""Unit tests for config.py."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from fanqie_short_story.config import Config, ConfigError, load_config


def test_load_config_minimal(tmp_path: Path, monkeypatch) -> None:
    cfg_yaml = tmp_path / "defaults.yaml"
    cfg_yaml.write_text(
        textwrap.dedent("""
            model: MiniMax-M2.7
            api_base: https://api.minimaxi.com/anthropic
            max_retries: 3
        """),
        encoding="utf-8",
    )
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test")
    cfg = load_config(cfg_yaml)
    assert cfg.model == "MiniMax-M2.7"
    assert cfg.api_key == "sk-test"
    assert cfg.max_retries == 3


def test_load_config_env_overrides_yaml(tmp_path: Path, monkeypatch) -> None:
    cfg_yaml = tmp_path / "defaults.yaml"
    cfg_yaml.write_text(
        "model: MiniMax-M2.7\napi_base: https://x\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-y")
    monkeypatch.setenv("FANQIE_STORY_MODEL", "MiniMax-M3")
    cfg = load_config(cfg_yaml)
    assert cfg.model == "MiniMax-M3"


def test_load_config_missing_api_key_raises(tmp_path: Path, monkeypatch) -> None:
    cfg_yaml = tmp_path / "defaults.yaml"
    cfg_yaml.write_text(
        "model: M\napi_base: https://x\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="MINIMAX_API_KEY"):
        load_config(cfg_yaml)


def test_load_config_missing_file_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "sk")
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_load_config_reads_nested_keys(tmp_path: Path, monkeypatch) -> None:
    cfg_yaml = tmp_path / "defaults.yaml"
    cfg_yaml.write_text(
        textwrap.dedent("""
            model: M
            api_base: https://x
            max_retries: 5
            critique:
              length_tolerance: 0.25
            body:
              default_temperature: 0.8
            outline:
              default_temperature: 0.5
            title:
              candidate_count: 3
            synopsis:
              target_length_chars: 100
            cover:
              default_backend: minimax
              image_size: [600, 800]
            genre_mapping:
              foo: bar
        """),
        encoding="utf-8",
    )
    monkeypatch.setenv("MINIMAX_API_KEY", "sk")
    cfg = load_config(cfg_yaml)
    assert cfg.max_retries == 5
    assert cfg.critique["length_tolerance"] == 0.25
    assert cfg.body["default_temperature"] == 0.8
    assert cfg.cover["image_size"] == [600, 800]
    assert cfg.genre_mapping == {"foo": "bar"}
