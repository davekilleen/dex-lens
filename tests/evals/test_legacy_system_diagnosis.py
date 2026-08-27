from __future__ import annotations

import json
from pathlib import Path

from tests.evals.legacy_system_fixture import (
    CANARY,
    FILES,
    complete_ledger,
    original_failure_ledger,
    write_legacy_system,
)

from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.evaluation.diagnosis import evaluate_diagnosis

EXPECTED = Path(__file__).parents[1] / "fixtures" / "evals" / "legacy-system-expected.json"

ORIGINAL_FAILURE_SHAPE = """# Diagnosis

## What I read
I looked at the system.

## Worth borrowing from Dex
The servers cover every tool and the same name means same capability.

## Fragility and contradictions
Written means running.

## What happens next
Nothing changed.
"""

COMPLETE_TWO_WAY_REPORT = """# Diagnosis

## What I read
- Inventory: invented legacy system

## What is working especially well
### Human-reviewed suggestions — Verified
> Show the suggestion first and wait for an explicit yes.
> - `skills/review-suggestions-custom/SKILL.md`

## What Dex should learn from you
### Role-outcome check-backs — Verified
> Tie each action to one role outcome and one dated check-back.
> - `skills/role-plan-custom/SKILL.md`

## Worth borrowing from Dex
### Current system health — Supported
> state: implemented
> - `System/system-doctor.py`

### Verified backup restore — Supported
> no recovery proof observed
> - `inventory-limits.md`

## Considered and rejected
- `career-development` — already shared after comparing the method.

## Fragility and contradictions
I checked the rules in `AGENTS.md` against the skills and found no conflicts.

## Coverage and limits
- Seven configured MCP doorways were found; their tool lists remain Unknown.
- Two scheduled jobs are written but live state was not assessed.

## What happens next
- Nothing has changed on this machine.
"""


def _expected() -> dict[str, object]:
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


def test_legacy_system_eval_rejects_the_original_bad_report(tmp_path: Path) -> None:
    fingerprint = write_legacy_system(tmp_path / "legacy")
    fingerprint = fingerprint.model_copy(update={"limits": ()})
    result = evaluate_diagnosis(
        fingerprint=fingerprint,
        ledger=original_failure_ledger(),
        report_markdown=ORIGINAL_FAILURE_SHAPE,
        expected=_expected(),
    )

    assert not result.passed
    assert any("tool inventory" in error for error in result.observation_errors)
    assert any("reciprocal" in error for error in result.report_errors)
    assert any("same-name" in error for error in result.comparison_errors)


def test_legacy_system_eval_accepts_a_grounded_two_way_report(tmp_path: Path) -> None:
    result = evaluate_diagnosis(
        fingerprint=write_legacy_system(tmp_path / "legacy"),
        ledger=complete_ledger(),
        report_markdown=COMPLETE_TWO_WAY_REPORT,
        expected=_expected(),
    )

    assert result.passed, result


def test_fixture_is_invented_and_fingerprint_retains_no_secret(tmp_path: Path) -> None:
    rendered = write_legacy_system(tmp_path / "legacy").model_dump_json()

    assert CANARY not in rendered
    assert all("dave" not in relative.lower() for relative in FILES)
    assert "nango" not in json.dumps(FILES).lower()
    assert "career-data" in {
        item.identity
        for item in write_legacy_system(tmp_path / "second").observations
        if item.kind is ObservationKind.MCP_SERVER
    }
