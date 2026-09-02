"""Skill drives the engine-owned guided work loop."""

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


def test_skill_drives_guided_work_without_stage_prompts() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "get_diagnosis_work" in text
    assert "process every engine-issued packet" in text.lower() or "fetch the next packet" in text
    assert "never ask the person to prompt the next diagnosis stage" in text.lower()
    assert "submit the specialist response unchanged" in text.lower()
    assert "up to ten" in text.lower()


def test_skill_has_parallel_and_sequential_host_routes() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "run independent packets in parallel" in text.lower()
    assert "process the same packets sequentially" in text.lower()
