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
    assert "dex-lens diagnosis advance" in text
    assert "dex-lens diagnosis submit" in text
    assert "dex-lens diagnosis result" in text
