"""Click CLI: fanqie-story generate / fanqie-story batch."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import click

from fanqie_short_story.config import Config, ConfigError, load_config
from fanqie_short_story.outline import GENRES, TONES
from fanqie_short_story.pipeline import GenerationFailed, generate_story


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
