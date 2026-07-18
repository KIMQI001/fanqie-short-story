"""Title candidates generator: 3-5 short hooky titles from body + hook.

v0.4.0 EXTENDS v0.1.0 with a tomato-flavored system prompt that hard-codes
the four title templates from tianyayu6/fanqie-hit-short-story methodology.md
(关系+事件+情绪 / 身份错位+行动 / 数字+反转 / 系统弹幕装置), enforces a
12-22 char length window, and bans abstract + template-flavor words that
the methodology flagged as 番茄平台 weak signals.
"""
from __future__ import annotations

from typing import Callable

from fanqie_short_story.body import Body
from fanqie_short_story.config import Config
from fanqie_short_story.llm import call_llm as default_llm
from fanqie_short_story.prompts import TITLE_USER_TEMPLATE


# v0.4.0 system prompt — tomato title patterns + banned vocabulary.
# Adapts tianyayu6/fanqie-hit-short-story methodology.md "番茄爆款标题模板".
_TITLE_SYSTEM_V040 = (
    "你是番茄爆款标题编辑。用户提供的核心梗已被扩成 10 章短篇大纲 + "
    "{n_chapters} 章正文。请给出 {n} 个候选标题。\n\n"
    "【番茄爆款标题模板】命中其一即可：\n"
    "  - 关系+事件+情绪：《我死后，前夫在我的遗物里疯了》\n"
    "  - 身份错位+行动：《真千金回家那天，我把户口迁走了》\n"
    "  - 数字+反转：《婚礼前夜，我收到了自己的死亡倒计时》\n"
    "  - 系统/弹幕装置：《弹幕说我是炮灰，我把全家送上热搜》\n\n"
    "【硬要求】\n"
    "  - 标题必须直给人物关系、核心事件、情绪结果\n"
    "  - 一行一个候选，不要编号、不要空行\n"
    "  - 长度 12-22 字之间\n\n"
    "【禁词】\n"
    "  - 抽象词：薄情、纠缠、宿命、此生、前世今生、轮回、无眠\n"
    "  - 模板化：虐恋（除非讽刺使用）、甜宠、爆款、首秀、巅峰\n"
)


def generate_titles(
    body: Body,
    hook: str,
    genre: str,
    *,
    n: int = 5,
    llm: Callable[..., str] = default_llm,
    config: Config | None = None,
) -> list[str]:
    body_head = body.text[:400]
    prompt = TITLE_USER_TEMPLATE.format(
        hook=hook, genre=genre, n=n, body_head=body_head,
    )
    # v0.4.0 system prompt — embed n + a chapter-count estimate so the LLM
    # knows it is generating titles for a finished 10-chapter novel, not a
    # partial draft.
    chapter_count_est = max(1, body.char_count // 1200)
    system = _TITLE_SYSTEM_V040.format(n=n, n_chapters=chapter_count_est)
    if config is not None:
        raw = llm(
            prompt, config=config, max_tokens=400, temperature=0.8,
            system=system,
        )
    else:
        raw = llm(prompt)
    titles = [t.strip() for t in raw.splitlines() if t.strip()]
    # Drop duplicates while preserving order, cap at n.
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= n:
            break
    return out
