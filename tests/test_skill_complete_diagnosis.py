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


def test_skill_requires_version_and_method_before_same_capability() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "A matching name is a candidate, not proof" in text
    assert "version distance" in text.lower()
    assert "A configured MCP server is not its tool list" in text
    assert "Written is not running" in text


def test_skill_requires_praise_reciprocity_and_three_or_fewer() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "What is working especially well" in text
    assert "What Dex should learn from you" in text
    assert "at most three" in text.lower()
    assert "repeat the best strength" in text


def test_skill_requires_engine_owned_catalogue_completeness() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "The engine owns the ledger" in text
    assert "Do not calculate or rewrite catalogue totals" in text
    assert "Unavailable entries cannot be recommended" in text
