# Changelog

## [v0.3.0] - 2026-07-16

### Added
- `fanqie-story daily run-once` — runs 5 stories/day from latest `fanqie-topic-scorer` scores.csv, with cover generation and substitute fallback (7-deep pool)
- `fanqie-story daemon {install,uninstall,status,run-once}` — manages a macOS launchd plist that runs the daily job at 06:00 local
- `daily_manifest.json` per-day audit trail (date, source_csv, generated, failures, totals)
- File lock at `~/.local/share/fanqie-short-story/daily.lock` (5-min timeout) — serializes concurrent scheduled + manual runs
- One new dependency: `filelock` (MIT, pure-Python)
- 1 new e2e test: `tests/e2e/test_daily_run_once.py` (gated by `-m e2e`; e2e tests are deselected by default via `pyproject.toml` `addopts`)

### Changed
- `__version__` → `0.3.0`
- `pyproject.toml` version → `0.3.0`; new console script `fanqie-story-run`
- `pyproject.toml` `[tool.pytest.ini_options]` adds `addopts = "-m 'not e2e'"` so bare `pytest` skips the e2e suite by default

## [v0.2.0] - 2026-07-16

### Added
- **LLM-based critic** (`llm_critique.py`): 5-aspect narrative review (hook strength / plot closure / character consistency / pacing / language). Runs after the heuristic pre-filter; failed critique → full body regenerate with critic's prose notes.
- `critique.llm_enabled` (default `true`): kill switch — set `false` to revert to v0.1.0 heuristic-only behavior.
- `critique.llm_max_tokens` (default `2000`): output token budget for the critic (MiniMax thinking-block headroom).
- `critique.llm_temperature` (default `0.3`): low temperature for stable verdicts.
- `critique.llm_max_calls_per_story` (default `3`): hard cap on critic calls per story, independent of retries.

### Manifest fields
- `critique_strategy`: `"heuristic_only"` or `"heuristic_then_llm"`.
- `heuristic_attempts`: int — number of heuristic runs.
- `llm_critic_attempts`: int — number of LLM critic runs (0 if heuristic always failed).
- `accepted_after_critic_cap`: bool — `true` if body was accepted because critic cap was reached.

### Changed
- `critique()` renamed to `heuristic_critique()` for clarity alongside the new LLM critic.

### Tests
- 59 unit tests pass (46 v0.1.0 + 8 new `llm_critique` + 5 new pipeline).
- 1 e2e test passes against real MiniMax-M2.7 + `cover_gen`.

## [v0.1.0] - 2026-07-16

Initial release. See `docs/superpowers/specs/2026-07-16-fanqie-short-story-design.md`.