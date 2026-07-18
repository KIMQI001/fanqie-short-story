"""Unit tests for critique.py."""
from __future__ import annotations

from fanqie_short_story.body import Body
from fanqie_short_story.critique import CritiqueReport, heuristic_critique


def _body(text: str) -> Body:
    return Body.from_text(text)


def test_critique_passes_on_good_body() -> None:
    # Body sized to ~6042 chars; target 6500 → v0.3.3 default range 3250-9750
    # → passes length. Old strict v0.1.0 range was 5200-7800; we keep the body
    # in BOTH so this single test asserts the loose defaults work.
    text = (
        "刀光剑影之间，林晚撞见了沈墨。她必须先发制人。"
        + ("情节推进中。" * 1000)
        + "真相大白，林晚归隐山林，从此再无风波。"
    )
    r = heuristic_critique(_body(text), hook="重生侯府", target_length=6500)
    assert isinstance(r, CritiqueReport)
    assert r.passed is True
    assert r.failed_gates == []


def test_critique_fails_when_weak_hook() -> None:
    # First 200 chars: pure setup, no conflict. Even with v0.3.3 default
    # min_hook_signals=1, zero hits still fails.
    text = (
        "在一个阳光明媚的早晨，我醒来了。今天天气真好。"
        "我起床洗漱，去厨房吃早餐。"
        + ("情节。" * 2000)
        + "结局圆满。"
    )
    r = heuristic_critique(_body(text), hook="重生侯府", target_length=4000)
    assert r.passed is False
    assert "hook" in r.failed_gates


def test_critique_fails_on_unresolved_ending() -> None:
    text = (
        "刀光剑影之间，林晚撞见了沈墨，她必须先发制人。"
        + ("推进。" * 2000)
        + "未完待续"
    )
    r = heuristic_critique(_body(text), hook="重生侯府", target_length=4000)
    assert "ending" in r.failed_gates


def test_critique_fails_on_length_out_of_window_strict() -> None:
    """Strict v0.1.0 contract (±20%): body of ~6142 chars at target 8000 fails."""
    text = (
        "刀光剑影之间，林晚撞见了沈墨。她必须先发制人。"
        + ("x" * 100)
        + "结局圆满收束。"
    )
    r = heuristic_critique(
        _body(text), hook="h", target_length=8000,
        length_tolerance=0.20,   # explicit strict kwarg
    )
    assert "length" in r.failed_gates


def test_critique_fails_on_pov_flip_strict() -> None:
    """Strict contract (pov >2): 3 voice swaps fail at cap=2.

    v0.4.1 update: chapter-boundary voice-swap counter replaces the
    broken `我[转身走向跑看听闻说想]` regex. A single-chapter body
    with mixed pronouns is NOT a POV swap any more — narration density
    is normal in first-person web fiction. This fixture now constructs
    a body with EXPLICIT alternating voice chapters.
    """
    ch_3rd_1 = "# 第一章\n\n" + ("她扑进母亲怀里，她哭着拥抱她。\n" * 30)
    ch_3rd_2 = "\n# 第三章\n\n" + ("他挡在她身前，他冷笑。\n" * 30)
    ch_3rd_3 = "\n# 第五章\n\n" + ("她看着他低头。\n" * 30)
    text = (
        ch_3rd_1
        + "\n# 第二章\n\n" + ("我转身走出去。\n" * 30)  # 1st-person
        + ch_3rd_2
        + "\n# 第四章\n\n" + ("我看着她，我问真相。\n" * 30)  # 1st
        + ch_3rd_3
        + "\n结局圆满收束。"
    )
    r = heuristic_critique(
        _body(text), hook="h", target_length=4000,
        max_pov_switches=2,   # explicit strict kwarg
    )
    # 3 third-person-dominant chapters (1, 3, 5) → 3 > cap 2 → fail.
    assert "pov" in r.failed_gates, (
        f"3 voice swaps at strict cap=2 should fail; "
        f"got failed_gates={r.failed_gates}"
    )


# ---------------------------------------------------------------------------
# v0.3.3: loosened defaults — match what real LLM output actually looks like.
# See critique.py docstring for the e2e-derived rationale.
# ---------------------------------------------------------------------------


def test_default_length_tolerance_is_50_percent() -> None:
    """v0.3.3 default length_tolerance=0.50; ~6200-char body at target 8000
    passes (window 4000-12000). At strict 0.20 it would fail."""
    text = (
        "刀光剑影之间，林晚撞见了沈墨。她必须先发制人。"
        + ("情节推进中。" * 1600)    # ~6400 chars total → 6400 < 8000 < 12000
        + "结局圆满收束。"
    )
    r = heuristic_critique(_body(text), hook="h", target_length=8000)
    assert "length" not in r.failed_gates


def test_default_max_pov_switches_is_8() -> None:
    """v0.3.3 default max_pov_switches=8; 5 switches passes. Old strict (3) failed."""
    text = (
        ("林晚冲向沈墨。" * 500)
        + ("我转过身去。" * 5)
        + ("沈墨扑向林晚。" * 500)
        + "结局圆满收束。"
    )
    r = heuristic_critique(_body(text), hook="h", target_length=4000)
    assert "pov" not in r.failed_gates


def test_default_min_hook_signals_is_1() -> None:
    """v0.3.3 default min_hook_signals=1; a body with one hook hit passes
    the hook gate. Old strict (≥2) failed."""
    text = (
        "刀光剑影之间，林晚撞见沈墨。"      # exactly 1 hook signal
        + ("情节推进中。" * 1000)
        + "真相大白，结局圆满收束。"
    )
    r = heuristic_critique(_body(text), hook="h", target_length=6500)
    assert "hook" not in r.failed_gates


def test_ending_signal_list_excludes_ellipsis() -> None:
    """v0.3.3: drop `...` and `……` from ending fail signals. LLM uses Chinese
    trailing-thought punctuation stylistically on resolved endings — they
    are NOT 'to be continued' markers. Keep `未完待续` etc."""
    text = (
        "刀光剑影之间，林晚撞见了沈墨。她必须先发制人。"
        + ("推进。" * 1000)
        + "真相大白。" + "……" * 5    # ellipsis tail, not a cliffhanger
    )
    r = heuristic_critique(_body(text), hook="h", target_length=6500)
    assert "ending" not in r.failed_gates
