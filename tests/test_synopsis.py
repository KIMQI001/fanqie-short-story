"""Unit tests for synopsis.py."""
from __future__ import annotations

from fanqie_short_story.body import Body
from fanqie_short_story.synopsis import (
    LeadParagraph,
    generate_lead,
    generate_synopsis,
)


def test_generate_lead_parses_three_segment_json() -> None:
    """generate_lead() parses {hook, conflict, protagonist_voice} from LLM."""
    body = Body(text="第一章\n\n" + "林晚睁开眼，发现自己重生了。" * 50, char_count=200)

    def fake(prompt, **kw):
        # Valid JSON for the three-segment lead.
        return (
            '{"hook":"林晚重生回到三年前", '
            '"conflict":"前世夫君正是凶手，退路只有七日", '
            '"protagonist_voice":"她不动声色，率先布局"}'
        )

    lead = generate_lead(body, "重生", "chuanqi", llm=fake)
    assert isinstance(lead, LeadParagraph)
    assert lead.hook == "林晚重生回到三年前"
    assert "前世夫君" in lead.conflict
    assert "率先布局" in lead.protagonist_voice
    # combined is the three segments joined with \n\n
    assert lead.combined == (
        "林晚重生回到三年前\n\n前世夫君正是凶手，退路只有七日\n\n"
        "她不动声色，率先布局"
    )


def test_generate_lead_handles_fenced_json() -> None:
    """```json ... ``` fences around the JSON object are tolerated."""
    body = Body(text="x", char_count=1)

    def fake(prompt, **kw):
        return (
            "```json\n"
            '{"hook":"h", "conflict":"c", "protagonist_voice":"p"}\n'
            "```"
        )

    lead = generate_lead(body, "h", "xianyan", llm=fake)
    assert lead.hook == "h"
    assert lead.conflict == "c"
    assert lead.protagonist_voice == "p"


def test_generate_lead_handles_prose_wrapped_json() -> None:
    """LLM may prefix with prose like 'Sure! Here is the JSON: {...}'."""
    body = Body(text="x", char_count=1)

    def fake(prompt, **kw):
        return (
            "好的，给你三段导语：\n"
            '{"hook":"x", "conflict":"y", "protagonist_voice":"z"}'
        )

    lead = generate_lead(body, "h", "xianyan", llm=fake)
    assert lead.hook == "x"
    assert lead.conflict == "y"


def test_generate_lead_falls_back_when_json_invalid() -> None:
    """Non-JSON LLM output → fallback uses body's first paragraph."""
    # Body has no \n\n split — fallback uses the full body up to n_chars.
    body = Body(text="林晚睁开眼发现自己重生了", char_count=14)

    def fake(prompt, **kw):
        return "not json at all"

    lead = generate_lead(body, "重生侯府", "chuanqi", llm=fake, n_chars=50)
    # Fallback path: combined = body text (no \n\n split), hook = hook[:60]
    assert lead.hook == "重生侯府"
    assert lead.conflict == ""
    assert lead.protagonist_voice == ""
    assert "林晚" in lead.combined


def test_generate_synopsis_shim_returns_combined_string() -> None:
    """v0.3.4 compat shim: returns combined as a single string."""
    body = Body(text="x", char_count=1)

    def fake(prompt, **kw):
        return (
            '{"hook":"h段", "conflict":"c段", "protagonist_voice":"p段"}'
        )

    syn = generate_synopsis(body, "h", "chuanqi", n=120, llm=fake)
    assert isinstance(syn, str)
    assert syn == "h段\n\nc段\n\np段"
