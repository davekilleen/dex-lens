"""The template the skill hands out must pass the gate the command enforces.

Two files have to agree about what a finished report looks like: the template
in `SKILL.md`, which is what the assistant writes to, and the check inside
`dex-lens reports save`, which is what refuses it. If they drift, the product
tells someone to write a report in a shape it will then reject, which is the
most infuriating kind of failure to debug from the outside.
"""

from __future__ import annotations

import re
from pathlib import Path

from capability_exchange.reports.store import missing_report_requirements

# The one canonical copy: inside the package, so the signed wheel ships it.
SKILL = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "capability_exchange"
    / "skill"
    / "dex-lens"
    / "SKILL.md"
)
_FENCE = re.compile(r"```markdown\n(.*?)```", re.DOTALL)


def _template() -> str:
    blocks = _FENCE.findall(SKILL.read_text(encoding="utf-8"))
    assert blocks, "SKILL.md must carry the report template as a markdown block"
    return max(blocks, key=len)


def test_the_report_template_would_be_accepted_by_the_save_command() -> None:
    assert missing_report_requirements(_template()) == []


def test_the_template_carries_the_sections_the_gate_requires() -> None:
    """Named explicitly, so a rename in either place fails here first."""
    template = _template().lower()

    for section in (
        "what i read",
        "what is working especially well",
        "what dex should learn from you",
        "worth borrowing from dex",
        "fragility and contradictions",
        "coverage and limits",
        "what happens next",
        "considered and rejected",
    ):
        assert section in template, section


def test_the_skill_tells_the_reader_the_save_command_can_refuse() -> None:
    """Being refused is only useful if it was expected."""
    skill = SKILL.read_text(encoding="utf-8")

    assert "dex-lens reports check" in skill
    assert "refuses a report that has not shown its work" in skill


def test_the_decisions_loop_is_closed() -> None:
    """Decisions recorded at the end must be read back at the start.

    The template's "What you decided" section is only worth writing if Phase
    0 instructs the next run to act on it — check on adoptions, respect
    declines. Recorded-but-never-read is how concierge memory quietly becomes
    theatre.
    """
    text = SKILL.read_text(encoding="utf-8")
    phase_zero = text[text.index("## Phase 0") : text.index("## Phase 1")]

    assert "What you decided" in phase_zero
    assert "Declined twice" in phase_zero
    assert "Taken" in phase_zero
    assert "Only if they ask what has changed" in phase_zero


def test_phase_zero_reads_the_selection_memory() -> None:
    """Design item 10: the focused selection and the never-examined remainder
    are read back at the start, so the next run can open with "last time you
    looked at X; these N areas have never had a deep dive — want one?"."""
    text = SKILL.read_text(encoding="utf-8")
    phase_zero = text[text.index("## Phase 0") : text.index("## Phase 1")]

    assert "selection memory" in phase_zero
    assert "never had a focused deep dive" in phase_zero
    assert "Share-back idea" in phase_zero
    assert "spans runs" in phase_zero


def test_phase_six_records_every_fate_for_the_next_run() -> None:
    """Design item 10: the fates recorded at Phase 6 are what Phase 0 reads."""
    text = SKILL.read_text(encoding="utf-8")
    phase_six = text[text.index("## Phase 6") : text.index("## Phase 7")]

    assert "What you decided" in phase_six
    assert "Share-back idea" in phase_six
    assert "Focused this run on" in phase_six


def test_the_template_carries_the_selection_and_share_back_lines() -> None:
    """The template's line shapes are what the store's memory parser reads."""
    template = _template()

    assert "- Focused this run on:" in template
    assert "- Explicitly not selected this run:" in template
    assert "- Share-back idea `" in template


def test_the_share_back_rules_record_a_parseable_fate_line() -> None:
    """"Once per idea, ever" only holds across runs if the fate is recorded
    in the exact line shape the next run's memory parser reads."""
    text = SKILL.read_text(encoding="utf-8")
    sharing = text[text.index("## Sharing an idea back") : text.index("## Phase 10")]

    assert "Share-back idea" in sharing
