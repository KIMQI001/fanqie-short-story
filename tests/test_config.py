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


def test_config_daily_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config.daily round-trips the 8 keys from defaults.yaml."""
    # load_config raises ConfigError if MINIMAX_API_KEY is unset; the round-trip
    # test only cares about the YAML merge, not API key validation, so setenv
    # a placeholder before calling load_config.
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test-round-trip-placeholder")
    from fanqie_short_story.config import load_config
    c = load_config(Path("config/defaults.yaml"))
    assert set(c.daily) == {
        "enabled", "top_n", "max_substitute_depth", "schedule_time",
        "notify", "scorer_root", "output_root", "log_dir",
    }
    assert c.daily["top_n"] == 5
    assert c.daily["max_substitute_depth"] == 7
    assert c.daily["schedule_time"] == "06:00"
    assert c.daily["scorer_root"] is None
