# Changelog

## [v0.3.3] - 2026-07-18

### Changed
- **Loosened `heuristic_critique` defaults** to match real LLM output. The v0.1.0 defaults (±20% length, pov >3, hook ≥2 from a 26-phrase list) were calibrated against a hand-picked hook fixture (`tests/e2e/test_real_generate.py`) that pre-satisfied all 4 gates. Against open-ended daily hooks, the v0.3.2 e2e diagnostic showed the strict defaults rejected ~70% of real LLM bodies:
  - `length_tolerance`: `0.20` → `0.50` (window 4000-12000 at target=8000)
  - `max_pov_switches`: `3` → `8` (real LLM bodies routinely have 4-7 我+verb matches)
  - `min_hook_signals`: hardcoded `2` → `1` (the LLM paraphrases the conflict — "斩杀"≠"杀了", "相逢"≠"撞见" — and rarely hits ≥2 of the 26 phrases in the first 200 chars)
  - `_ENDING_FAIL_SIGNALS`: dropped `...` and `……` (legitimate Chinese trailing-thought punctuation, not "to be continued" markers)
- **`config/defaults.yaml` `critique:` block updated to match the new defaults** (`length_tolerance: 0.50`, `max_pov_switches: 8`). The `length_tolerance` key is the only one already consumed by `pipeline.py`; the others are still function defaults. Pass explicit kwargs to `heuristic_critique` to recover strict v0.1.0–v0.3.2 behavior.

### Tests
- 106 unit tests pass (102 v0.3.2 + 4 new tests for the loosened defaults).
- 2 existing tests that hardcoded at the strict legacy defaults now pass explicit kwargs (`length_tolerance=0.20`, `max_pov_switches=3`) so they keep testing the strict contract.
- E2E not re-run for this change; expected impact: ≥3/5 success rate on `daily run-once` based on the v0.3.2 gate-failure histogram (hook 71% + length 54% + ending 46% + pov 38% combined → <30% with strict, >60% with loose).

## [v0.3.2] - 2026-07-17

### Fixed
- **`daily.py` `_run_daily_unlocked` now passes `target_length=8000` to `generate_story`** (was `12000`). The pipeline's `±20%` length tolerance gives a window of `6400-9600` for target=8000, which matches the only known-good heuristic calibration: v0.1.0/v0.2.0's `tests/e2e/test_real_generate.py` uses `target_length=8000` with `±50%` length tolerance (4000-12000) — the heuristic was validated only against that hand-picked hook fixture and never re-validated for open-ended daily hooks at 12000. v0.3.0/v0.3.1's `12000 ±20%` (9600-14400) is too narrow for real LLM output: the v0.3.1 diagnostic e2e run showed bodies of 4618/6566/8024/12042 chars, with 3/4 failing the length gate (2 below 9600, 1 above 14400). Regression test: `test_run_daily_passes_target_length_8000`.

## [v0.3.1] - 2026-07-16

### Fixed
- **`config/defaults.yaml` `genre_mapping` now covers all 10 fanqie-topic-scorer sub-genres** (`xuanhuan-xiuzhen`, `xuanhuan-chuantong`, `dushi-richang`, `dushi-zhongtian`, `yanqing-gufeng`, `yanqing-xuanhuan`, `yanqing-haomen`, `yanqing-tianchong`, `kehuan-moshi`, `xuanyi-naodong`). The earlier hand-curated list had a typo (`dushi-rich` instead of `dushi-richang`) and missed 7 of the 10 actual sub-genres — caught by the e2e test run against the live scorer, which surfaced `ValueError: Unknown genre: 'dushi-richang'` for 3 of 12 attempts.
- **`daily.py` now applies `config.genre_mapping` before calling `generate_story`**. v0.3.0 passed the scorer's fine-grained sub-genre (e.g. `xuanhuan-xiuzhen`, `kehuan-moshi`) straight through, which failed at the pipeline's `ValueError: Unknown genre` check — meaning v0.3.0 daily automation would have never produced a story against the real scorer output. The `batch` CLI has translated these since v0.1.0 via `config.genre_mapping.get(source, source)`; `daily` now mirrors that. Unmapped genres pass through unchanged. Regression tests: `test_run_daily_translates_csv_genre_via_config_mapping`, `test_default_genre_mapping_covers_all_topic_scorer_subgenres`.

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