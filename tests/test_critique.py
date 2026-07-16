"""Unit tests for critique.py."""
from __future__ import annotations

from fanqie_short_story.body import Body
from fanqie_short_story.critique import CritiqueReport, heuristic_critique


def _body(text: str) -> Body:
    return Body.from_text(text)


def test_critique_passes_on_good_body() -> None:
    # Body sized to ~6042 chars; target 6500 → range 5200-7800 → passes length.
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
    # First 200 chars: pure setup, no conflict.
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


def test_critique_fails_on_length_out_of_window() -> None:
    text = (
        "刀光剑影之间，林晚撞见了沈墨，她必须先发制人。"
        + ("x" * 100)
        + "结局圆满收束。"
    )
    r = heuristic_critique(_body(text), hook="h", target_length=8000)
    assert "length" in r.failed_gates


def test_critique_fails_on_pov_flip() -> None:
    text = (
        ("林晚冲向沈墨。" * 500)
        + ("我转过身去。" * 5)
        + ("沈墨扑向林晚。" * 500)
        + "结局圆满收束。"
    )
    r = heuristic_critique(_body(text), hook="h", target_length=4000)
    # Heuristic: "我" appearing with POV-action verbs in a third-person body = POV flip.
    assert "pov" in r.failed_gates
