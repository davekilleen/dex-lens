"""The skill follows engine truth. It does not keep its own diagnosis books."""

from __future__ import annotations

from pathlib import Path

SKILL = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "capability_exchange"
    / "skill"
    / "dex-lens"
    / "SKILL.md"
)


def test_skill_uses_engine_status_instead_of_keeping_its_own_checklist() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "dex-lens diagnosis status" in text
    assert "Do not calculate or rewrite catalogue totals" in text
    assert "A diagnosis ends only when the engine returns `closed`" in text


def test_skill_keeps_the_packaged_fallback_verified_and_engine_owned() -> None:
    text = SKILL.read_text(encoding="utf-8")
    fallback = text[
        text.index("### The bundled signed snapshot") : text.index("## Phase 5")
    ]
    prose = " ".join(fallback.split())

    assert "normal pinned Dex key ring" in prose
    assert "current enriched catalogue is authoritative" in prose
    assert "Fallback facts are never merged" in prose
    assert "Do not open, copy, combine or interpret it yourself" in prose
    assert "dex-lens diagnosis status" in fallback
    assert "dex-lens diagnosis result" in fallback
    assert "supplement" not in fallback


def test_skill_keeps_repairs_and_sharing_outside_diagnosis() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "start a separate, explicitly approved flow" in text
    assert "A preview is not a share receipt" in text


def test_skill_names_every_generated_close_field() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "the strongest grounded thing they are already doing" in text
    assert "what Dex should learn, or the exact honest empty answer" in text
    assert "the single best first move, if one cleared the bar" in text
    assert "where the report was saved" in text
    assert "how to return to the run" in text
    assert "the separate sharing and future-watch choices" in text


def test_skill_has_no_independent_numeric_coverage_examples() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "Never invent a score." in text
    assert "93 covered" not in text
    assert "93 already covered" not in text
    assert "7/10" not in text


def test_skill_names_the_engine_commands() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "dex-lens diagnosis prepare" in text
    assert "dex-lens diagnosis approve" in text
    assert "dex-lens diagnosis advance" in text
    assert "dex-lens diagnosis submit" in text
    assert "dex-lens diagnosis result" in text
    assert "prepare --root <folder> --wait" not in text


def test_skill_treats_a_first_look_as_fresh_not_a_delta() -> None:
    text = SKILL.read_text(encoding="utf-8")
    phase_zero = text[text.index("## Phase 0") : text.index("## Phase 1")]

    assert "A first look is the default" in phase_zero
    assert "what Dex has that I don't" in phase_zero
    assert "Do not open with `dex-lens reports --last`" in phase_zero
    assert "Ignore last report" in phase_zero
    assert "fresh eyes" in phase_zero
    assert "do not read the last report" in phase_zero
    assert "Do not ask which folder first" in phase_zero

    opening, fence, remainder = phase_zero.partition("```")
    assert "Do not open with `dex-lens reports --last`" in opening
    assert "Only if they ask what has changed" in opening
    assert fence
    assert remainder.lstrip().startswith("dex-lens reports --last")
