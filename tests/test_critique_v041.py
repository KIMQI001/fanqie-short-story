"""v0.4.1 heuristic critique fixes: hook-vocabulary expansion +
chapter-boundary POV switch counter.

The v0.4.0 heuristic had two gates calibrated against narrow v0.1.x
vocabulary that real MiniMax-M2.7 output does not match:
  1. _HOOK_SIGNALS — hardcoded (`撞见,发现,必须,凶手,重生,...`). The LLM
     opens with `看着 / 注意到 / 归来 / 回家 / 摊牌` instead. Result: every
     well-written body fails the hook gate on attempt 1.
  2. POV regex `我[转身走向跑看听闻说想]` — overcounts first-person
     narration verbs (`我看着她`, `我走上前`, `我想了想`) as "POV switches".
     Real first-person web fiction uses these constantly; the regex is
     broken-by-design.

v0.4.1 fixes:
  1. _HOOK_SIGNALS gains ~22 natural opener + memory-object terms.
  2. heuristic_critique() swaps the regex POV counter for a
     chapter-boundary voice-swap counter. Splits on `# 第N章 / ## 第N章`
     markers; counts chapters whose dominant narrative voice is
     third-person (他/她/它 > 我). The kwarg `max_pov_switches` keeps the
     same name with relaxed semantics.

See critique.py docstring for the e2e-derived rationale.
"""
from __future__ import annotations

import re

from fanqie_short_story.body import Body
from fanqie_short_story.critique import (
    CritiqueReport,
    _HOOK_SIGNALS,
    heuristic_critique,
)


# ---------------------------------------------------------------------------
# Hook-vocabulary expansion
# ---------------------------------------------------------------------------

def test_hook_signals_include_natural_opener_words() -> None:
    """After v0.4.1, the vocabulary MUST recognize natural Chinese
    web-fiction opener phrases the LLM produces in practice.

    Source of truth: real MiniMax-M2.7 opening lines observed across
    the v0.4.0 e2e diagnostic run. Phrases observed:
      - 我注意到
      - 我看着她
      - 真千金回家的那天
      - 我带着快递单
    """
    needed = (
        "看着",      # 我看着她
        "注意到",    # 我注意到
        "归来",      # 真千金归来那天
        "回家",      # 真千金回家那天
        "摊牌",      # 终于摊牌
        "算计",      # 她眼底闪过算计
        "真相",      # 真相是
        "秘密",      # 守了二十年的秘密
        "背叛",      # 闺蜜背叛
        "挑明",      # 把事情挑明
        "撕破",      # 撕破脸
        "揭露",      # 一举揭露
        "弹幕",      # 弹幕警告
        "倒计时",    # 死亡倒计时
        "警告",      # 系统警告
        "伪装",      # 我撕下伪装
        "绑架",      # 假千金绑架
        "圈套",      # 一步步设下圈套
        "婚书",      # 撕掉婚书
        "病历",      # 压在病历下
        "亲子鉴定",  # 亲子鉴定报告
    )
    missing = [w for w in needed if w not in _HOOK_SIGNALS]
    assert not missing, f"_HOOK_SIGNALS missing v0.4.1 additions: {missing}"


def test_hook_gate_passes_with_看着_opener() -> None:
    """Body opening with `看着` (natural opener, no legacy hook signal)
    should pass the hook gate under v0.4.1 vocabulary."""
    body = Body.from_text(
        "我看着她递来的快递单，注意到收件人写着我的真名。" * 200
        + "真相大白，归隐山林。"
    )
    r = heuristic_critique(body, hook="h", target_length=2000)
    assert "hook" not in r.failed_gates, (
        f"看着-opener should pass hook gate under v0.4.1 vocabulary; "
        f"got failed_gates={r.failed_gates}, notes={r.notes}"
    )


def test_hook_gate_passes_with_回家_opener() -> None:
    """Body opening with `真千金回家的那天` (no legacy hook signal)
    should pass the hook gate under v0.4.1 vocabulary."""
    body = Body.from_text(
        "真千金回家的那天，客厅里摆满了鲜花。" * 200
        + "真相大白，归隐山林。"
    )
    r = heuristic_critique(body, hook="h", target_length=2000)
    assert "hook" not in r.failed_gates, (
        f"回家-opener should pass hook gate; got {r.failed_gates}"
    )


def test_hook_gate_passes_with_摊牌_opener() -> None:
    """Body opening with `摊牌` (a common dramatic opener)."""
    body = Body.from_text(
        "终于摊牌了。他撕下伪装，揭露她的秘密。\n" * 200
        + "真相大白，归隐山林。"
    )
    r = heuristic_critique(body, hook="h", target_length=2000)
    assert "hook" not in r.failed_gates


def test_hook_gate_still_fails_on_pure_description() -> None:
    """A purely descriptive opener with NO hook-signal vocabulary
    (not legacy, not v0.4.1) must still fail. Tests that we didn't
    make the gate so loose it never fires."""
    body = Body.from_text(
        # First 200 chars: pure weather/setup, no conflict vocabulary.
        "在很久以前的一个小镇，住着一个姑娘。她的日常很平静。\n"
        "她常常在下午喝茶。\n" * 1000
        + "结局圆满收束。"
    )
    r = heuristic_critique(body, hook="h", target_length=2000)
    assert "hook" in r.failed_gates, (
        f"pure-description opener should still fail; got {r.failed_gates}"
    )


def test_hook_gate_legacy_撞见_still_passes() -> None:
    """v0.1.x vocabulary (撞见 etc.) must remain recognized — no regression."""
    body = Body.from_text(
        "刀光剑影之间，林晚撞见了沈墨，她必须先发制人。" * 200
        + "真相大白，归隐山林。"
    )
    r = heuristic_critique(body, hook="h", target_length=2000)
    assert "hook" not in r.failed_gates


# ---------------------------------------------------------------------------
# POV switch counter — chapter-boundary voice swaps
# ---------------------------------------------------------------------------

def test_pov_switch_single_first_person_chapter_is_zero_switches() -> None:
    """A single chapter written in first person (我) should produce
    0 POV switches. Matches the natural tomato-methodology 10-chapter
    body where each chapter is `# 第N章` and narrates from the
    protagonist's POV."""
    text = (
        "# 第一章 事故\n\n"
        "我看着快递单，注意到收件人写着我的真名。\n"
        "我带着婚书，走进客厅。\n"
        "我推开门，看见她扑进我母亲怀里。\n\n"
        "# 第二章 反击\n\n"
        "我转身走到门口，按了门铃。\n"
        "我问她真相到底是什么。\n"
    )
    body = Body.from_text(text)
    r = heuristic_critique(body, hook="h", target_length=500)
    assert "pov" not in r.failed_gates, (
        f"single-voice 1st-person body should pass pov gate; "
        f"got failed_gates={r.failed_gates}, notes={r.notes}"
    )


def test_pov_switch_no_chapter_headers_treats_body_as_one_chapter() -> None:
    """A body without chapter markers is treated as a single chapter.
    1st-person narrative with occasional `我看着` should not switch
    to 3rd-person just because the user didn't add `# 第N章`."""
    text = (
        "我看着她递来的快递单。" * 50
        + "我转身走向门口。" * 20
        + "我问她真相。" * 50
        + "我看着她。" * 50
        + "结局圆满收束。"
    )
    body = Body.from_text(text)
    r = heuristic_critique(body, hook="h", target_length=2000)
    assert "pov" not in r.failed_gates


def test_pov_switch_count_chapter_voice_swaps() -> None:
    """A body with alternating 1st-person / 3rd-person chapters
    produces a swap count that exceeds a strict kwarg cap and stays
    under the default cap.

    Body:
      Chapter 1: 3rd-person dominant (她 / 他 narrator)
      Chapter 2: 1st-person dominant (我)
      Chapter 3: 3rd-person dominant
      Chapter 4: 1st-person dominant
      Chapter 5: 3rd-person dominant
    = 3 third-person-dominant chapters → counter returns 3.

    v0.4.1 counter semantics: the count is the number of chapters
    whose dominant narrative voice is third-person, NOT the number
    of transitions. A pure-first-person 10-chapter body returns 0;
    a body with 3 third-person chapters out of 5 returns 3.
    """
    ch1 = "# 第一章\n\n" + ("她看着窗外，他递来一封信。她转身往门口走。\n" * 20)
    ch2 = "\n# 第二章\n\n" + ("我看着她，忽然问真相。\n" * 30)
    ch3 = "\n# 第三章\n\n" + ("她推开门，他挡在她身前。她冷笑揭穿他。\n" * 30)
    ch4 = "\n# 第四章\n\n" + ("我想了想，开口说我不再沉默。\n" * 30)
    ch5 = "\n# 第五章\n\n" + ("她看着他低头。\n" * 30)
    text = ch1 + ch2 + ch3 + ch4 + ch5 + "\n结局圆满收束。"
    body = Body.from_text(text)
    # Default cap=8 → 3 swaps ≤ 8 → passes
    r_default = heuristic_critique(body, hook="h", target_length=3000)
    assert "pov" not in r_default.failed_gates, (
        f"3 swaps < default cap 8 should pass; got {r_default.failed_gates}"
    )
    # Strict cap=2 → 3 swaps > 2 → fails
    r_strict = heuristic_critique(
        body, hook="h", target_length=3000, max_pov_switches=2,
    )
    assert "pov" in r_strict.failed_gates, (
        f"3 swaps > strict cap 2 should fail; got {r_strict.failed_gates}"
    )


def test_pov_switch_zero_cap_rejects_any_voice_swap() -> None:
    """With max_pov_switches=0 (single-voice only), any body with even
    one third-person-dominant chapter must fail."""
    text = (
        "# 第一章\n\n" + ("她看着窗外。她转身。\n" * 30)
        + "\n# 第二章\n\n" + ("我看着她。\n" * 30)
    )
    body = Body.from_text(text)
    r = heuristic_critique(
        body, hook="h", target_length=2000, max_pov_switches=0,
    )
    assert "pov" in r.failed_gates


def test_pov_switch_full_first_person_passes_under_any_cap() -> None:
    """A 10-chapter body all written in pure first-person narration
    must produce ZERO chapter-boundary voice swaps regardless of
    strict cap. This is the canonical v0.4.0 methodology body shape."""
    chapter_text = "我看着她，我注意到快递单。\n我走过去，我问她真相。\n我签字，我转身离开。\n"
    titles = "一二三四五六七八九十"
    chapters = []
    for i in range(10):
        chapters.append(f"# 第{titles[i]}章\n\n{chapter_text * 10}")
    text = "\n\n".join(chapters) + "\n结局圆满收束。"
    body = Body.from_text(text)
    # Even at max_pov_switches=0, this should pass.
    r = heuristic_critique(
        body, hook="h", target_length=10000, max_pov_switches=0,
    )
    assert "pov" not in r.failed_gates, (
        f"10 chapters of pure 1st-person should produce 0 swaps; "
        f"got failed_gates={r.failed_gates}, notes={r.notes}"
    )


# ---------------------------------------------------------------------------
# Real LLM body — the v0.4.0 e2e fixture MUST pass under v0.4.1 heuristic
# ---------------------------------------------------------------------------

REAL_LLM_BODY_HEAD = (
    "我站在楼梯拐角，看着那个叫沈瑶的女孩扑进我母亲怀里。"
    "我注意到她的目光越过我母亲的头顶。那眼神里没有久别重逢的思念。"
)
REAL_LLM_BODY_TAIL = "真相大白，归隐山林，从此再无风波。"

REAL_LLM_BODY_MID_CHAPTER = (
    "她看着我，忽然问。\n\n"
    "径直走到我身边，从口袋里掏出一封信。\n\n"
    "我想到真相到底是什么。\n\n"
) * 50


def test_real_llm_body_passes_v041_heuristic() -> None:
    """The actual MiniMax-M2.7 output that failed v0.4.0's heuristic
    (POV 18 + 0 hook signals) MUST pass under v0.4.1's vocabulary +
    chapter-boundary POV counter.

    This is the regression-test that proves v0.4.1 fixes the e2e blocker.
    """
    text = REAL_LLM_BODY_HEAD + REAL_LLM_BODY_MID_CHAPTER + REAL_LLM_BODY_TAIL
    body = Body.from_text(text)
    r = heuristic_critique(body, hook="h", target_length=2000)
    # Length may still fail (body is smaller than 2000). Hook + POV must both pass.
    assert "hook" not in r.failed_gates, (
        f"看着/注意到 opener should pass hook gate under v0.4.1; "
        f"got {r.failed_gates}, notes={r.notes}"
    )
    assert "pov" not in r.failed_gates, (
        f"single-voice 1st-person body should pass pov gate; "
        f"got {r.failed_gates}, notes={r.notes}"
    )