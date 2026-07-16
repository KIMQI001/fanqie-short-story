# fanqie-short-story

Self-use CLI: generate 番茄短故事 (1-2万字) from a hook + genre + target length.

## Install

```bash
git clone ... && cd fanqie-short-story && pip install -e ".[dev]"
```

## Configure

```bash
export MINIMAX_API_KEY=sk-cp-...
```

## Usage

```bash
# Single story
fanqie-story generate \
  --hook "重生后我成了侯府嫡女，发现前世夫君是害我的凶手" \
  --genre chuanqi \
  --length 12000 \
  --output-dir /tmp/fanqie-stories

# Batch from a fanqie-topic-scorer weekly report
fanqie-story batch \
  --from-report ~/CascadeProjects/projects/fanqie-topic-scorer/output/runs/2026-W29/scores.csv \
  --genre chuanqi --length 12000 --limit 3 \
  --output-dir /tmp/fanqie-stories
```

Output (per story):

```
<output-dir>/<slug>/
├── outline.md          # 5-8 幕 + 人物 + 设定 + 核心冲突
├── body.txt            # 正文 plain text, 分章节用空行分隔
├── titles.txt          # 3-5 个候选标题
├── synopsis.md         # 简介 50-200 字
├── cover.jpg           # 600×800 封面 (来自 cover_gen)
└── manifest.json       # 总览: hook / genre / length / backend / cost / 审计
```

## Publishing

This tool does NOT auto-publish to 番茄 (account-ban risk). It produces local files
for manual paste into 番茄作家后台. Recommended workflow:

1. `fanqie-story generate ...` to produce a story
2. Open `titles.txt`, pick one title
3. Paste `body.txt` into 番茄作家后台 正文
4. Paste `synopsis.md` content into 简介
5. Upload `cover.jpg` as 封面
6. Pick a 标签 and 提交审核

## Architecture

See `docs/superpowers/specs/2026-07-16-fanqie-short-story-design.md` (in the
`book` repo). Reuses:
- `fanqie-topic-scorer` for input (read `scores.csv` directly)
- `cover_gen` for cover (subprocess call to `cover_gen generate`)
- `MiniMax-M2.7` for LLM (same endpoint as fanqie-topic-scorer)

## Tests

```bash
pytest tests/ -m "not e2e" -q       # unit + integration
pytest tests/e2e -m e2e -q          # against real LLM (requires API key)
```
