"""Click CLI: fanqie-story generate / fanqie-story batch."""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import click

from fanqie_short_story.config import Config, ConfigError, load_config
from fanqie_short_story.outline import GENRES, TONES
from fanqie_short_story.pipeline import GenerationFailed, generate_story
from fanqie_short_story import daily as daily_mod
from fanqie_short_story import daemon as daemon_mod
from fanqie_short_story.daily import run_daily
from fanqie_short_story.daemon import (
    LOG_DIR,
    install,
    status,
    uninstall,
)


_DEFAULT_CONFIG = Path("config/defaults.yaml")


def _resolve_config(ctx: click.Context, param, value: str | None) -> Config:
    path = Path(value) if value else _DEFAULT_CONFIG
    try:
        return load_config(path)
    except ConfigError as e:
        raise click.ClickException(str(e))


@click.group()
@click.option("--config", default=None,
              help="Path to defaults.yaml (default: config/defaults.yaml)")
@click.pass_context
def main(ctx: click.Context, config: str | None) -> None:
    """fanqie-short-story: generate 番茄短故事 from a hook + genre."""
    ctx.obj = _resolve_config(ctx, None, config)


@main.command()
@click.option("--hook", required=True, help="短篇核心钩子")
@click.option("--genre", required=True, type=click.Choice(list(GENRES)),
              help="短篇类型")
@click.option("--length", required=True, type=int,
              help="目标字数（1-3万字）")
@click.option("--tone", default=None, type=click.Choice(list(TONES)),
              help="风格，默认按类型选")
@click.option("--output-dir", default="output/stories", type=click.Path(),
              help="输出根目录（每个 story 一个子目录）")
@click.option("--slug", default=None,
              help="目录名（默认从 hook 推导）")
@click.option("--cover-backend", default="auto",
              type=click.Choice(["auto", "minimax", "comfyui"]),
              help="封面生成后端")
@click.pass_context
def generate(ctx: click.Context, hook: str, genre: str, length: int,
             tone: str | None, output_dir: str, slug: str | None,
             cover_backend: str) -> None:
    """Generate one short story end-to-end."""
    config: Config = ctx.obj
    try:
        out = generate_story(
            hook=hook, genre=genre, target_length=length,
            tone=tone, output_dir=Path(output_dir), slug=slug,
            config=config, cover_backend=cover_backend,
        )
    except FileExistsError as e:
        raise click.ClickException(str(e))
    except GenerationFailed as e:
        click.echo(f"generation failed: {e}", err=True)
        click.echo(f"artifacts (with last failed body) in: {e.output_dir}",
                   err=True)
        sys.exit(1)
    click.echo(f"✓ story written to: {out}")


@main.command("batch")
@click.option("--from-report", "from_report", required=True,
              type=click.Path(exists=True),
              help="fanqie-topic-scorer 报告路径 (scores.csv)")
@click.option("--genre", required=True, type=click.Choice(list(GENRES)),
              help="短篇类型（覆盖默认值）")
@click.option("--length", default=12000, type=int,
              help="目标字数（默认 12000）")
@click.option("--limit", default=3, type=int,
              help="从报告 top-N 选几篇（默认 3）")
@click.option("--output-dir", default="output/stories", type=click.Path())
@click.pass_context
def batch(ctx: click.Context, from_report: str, genre: str,
          length: int, limit: int, output_dir: str) -> None:
    """Generate N short stories from a fanqie-topic-scorer report."""
    config: Config = ctx.obj
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    with open(from_report, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    rows.sort(key=lambda r: float(r.get("score", 0) or 0), reverse=True)
    rows = rows[:limit]

    for i, row in enumerate(rows, start=1):
        rank = row.get("rank", str(i))
        title = row.get("title", f"row-{rank}")
        rationale = row.get("rationale", "")
        source_genre = row.get("genre", "")
        mapped_genre = config.genre_mapping.get(source_genre, genre)
        hook = f"{title}：{rationale[:80]}" if rationale else title
        slug = f"batch-{rank}-{title[:20]}"

        click.echo(f"[{i}/{len(rows)}] generating from rank {rank} ({title}) → {slug}")
        try:
            out = generate_story(
                hook=hook, genre=mapped_genre, target_length=length,
                tone=None, output_dir=output_dir_path, slug=slug,
                config=config,
            )
            click.echo(f"  ✓ {out}")
        except (FileExistsError, GenerationFailed) as e:
            click.echo(f"  ✗ {e}", err=True)
            continue


# ---------------------------------------------------------------------------
# v0.3.0: `daily` and `daemon` groups (Task 13)
# ---------------------------------------------------------------------------


@main.group()
def daily() -> None:
    """Daily automated story generation (v0.3.0)."""


@daily.command("run-once")
@click.option("--config", default="config/defaults.yaml")
@click.option("--scorer-root", default=None,
              help="Path to fanqie-topic-scorer repo (default: ~/CascadeProjects/projects/fanqie-topic-scorer)")
@click.option("--output-root", default="output/daily", type=click.Path())
@click.option("--top-n", default=5, type=int)
@click.option("--max-substitute-depth", default=7, type=int)
@click.option("--notify/--no-notify", default=True)
@click.pass_context
def daily_run_once(ctx: click.Context, config: str, scorer_root: str | None,
                   output_root: str, top_n: int, max_substitute_depth: int,
                   notify: bool) -> None:
    """Run one daily batch (5 stories by default)."""
    cfg: Config = ctx.obj
    if scorer_root is None:
        scorer_root = str(daily_mod.DEFAULT_SCORER_ROOT)
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    try:
        result = run_daily(
            config=cfg,
            scorer_root=Path(scorer_root),
            output_root=output_root_path,
            top_n=top_n,
            max_substitute_depth=max_substitute_depth,
        )
    except daily_mod.DailyRunError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except FileNotFoundError as e:
        click.echo(f"daily: {e}", err=True)
        sys.exit(1)
    if notify:
        succeeded = len(result.generated)
        if succeeded == top_n:
            msg = f"今天 {succeeded}/{top_n} 篇生成完"
        elif succeeded == 0:
            msg = f"⚠️ 今日 0/{top_n} 篇生成失败，详情见 logs/daily/"
        else:
            failed = top_n - succeeded
            msg = f"今天 {succeeded}/{top_n} 篇生成完 ({failed} 篇失败)"
        try:
            daemon_mod._fire_osascript("番茄短篇", "", msg)
        except Exception:
            pass  # notification is best-effort
    click.echo(f"daily: {len(result.generated)}/{top_n} succeeded, "
               f"{len(result.failures)} failed, api_calls={result.api_calls}")


@main.group()
def daemon() -> None:
    """Manage macOS launchd scheduling (v0.3.0)."""


@daemon.command("install")
@click.option("--time", "schedule_time", default="06:00",
              help="Local time to run daily (HH:MM, default 06:00)")
@click.option("--scorer-root", default=None,
              help="Path to fanqie-topic-scorer repo")
@click.option("--fanqie-story-root", default=None,
              help="Path to this fanqie-short-story repo (default: auto-detect via git rev-parse)")
@click.option("--force/--no-force", default=False)
@click.option("--update-env/--no-update-env", default=False)
def daemon_install(schedule_time: str, scorer_root: str | None,
                   fanqie_story_root: str | None, force: bool,
                   update_env: bool) -> None:
    """Install the daily launchd plist."""
    # Auto-detect scorer_root if not provided (spec §10: discovery is best-effort)
    if scorer_root is None:
        for cand in [
            Path.home() / "CascadeProjects" / "projects" / "fanqie-topic-scorer",
            Path.home() / "projects" / "fanqie-topic-scorer",
        ]:
            if cand.is_dir():
                scorer_root = str(cand)
                break
    if scorer_root is None:
        click.echo(
            "Could not auto-detect scorer_root. Pass --scorer-root <path>.",
            err=True,
        )
        sys.exit(1)
    if fanqie_story_root is None:
        fanqie_story_root = str(Path.cwd())  # sensible default
    try:
        install(
            schedule_time=schedule_time,
            scorer_root=Path(scorer_root),
            fanqie_story_root=Path(fanqie_story_root),
            force=force,
            update_env=update_env,
        )
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except FileExistsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    click.echo(f"installed: {daemon_mod.PLIST_PATH}")


@daemon.command("uninstall")
def daemon_uninstall() -> None:
    """Remove the daily launchd plist."""
    uninstall()
    click.echo(f"uninstalled: {daemon_mod.PLIST_PATH}")


@daemon.command("status")
def daemon_status() -> None:
    """Show daily launchd status."""
    r = status()
    click.echo(f"  installed:     {r.installed}")
    click.echo(f"  loaded:        {r.loaded}")
    click.echo(f"  plist_path:    {r.plist_path}")
    click.echo(f"  schedule_time: {r.schedule_time}")
    click.echo(f"  env_key:       {r.env_key_present}")
    if r.last_run_log:
        click.echo(f"  last_run_log:  {r.last_run_log}")
    else:
        click.echo(f"  last_run_log:  (none)")


@daemon.command("run-once")
@click.option("--config", default="config/defaults.yaml")
@click.option("--log-dir", default=None, type=click.Path())
@click.pass_context
def daemon_run_once(ctx: click.Context, config: str, log_dir: str | None) -> None:
    """Run one daily batch (the plist's ProgramArguments target)."""
    if log_dir is None:
        log_dir = str(LOG_DIR)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    cfg: Config = ctx.obj
    rc = daemon_mod.run_once(
        config_path=Path(config),
        log_dir=Path(log_dir),
        scorer_root=os.environ.get("FANQIE_SCORER_ROOT", str(daily_mod.DEFAULT_SCORER_ROOT)),
    )
    sys.exit(rc)
