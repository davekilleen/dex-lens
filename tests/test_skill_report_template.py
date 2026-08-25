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
        "contradictions and fragility",
        "what happens next",
        "considered and rejected",
    ):
        assert section in template, section


def test_the_skill_tells_the_reader_the_save_command_can_refuse() -> None:
    """Being refused is only useful if it was expected."""
    skill = SKILL.read_text(encoding="utf-8")

    assert "dex-lens reports check" in skill
    assert "refuses a report that has not shown its work" in skill
