"""The grader entry point the acceptance loop actually runs.

`scripts/run_wow_gate.py` had no test at all, while being the one command
whose output is recorded as the evidence a run passed. These cover the three
things that matter about it: that it discriminates, that it cannot be pointed
at someone else's audit, and that what it writes carries nothing from the
inspected system.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.evals.test_wow_gate import (
    _another_runs_audit,
    _fabricated_ledger,
    _ledger,
    autonomous_audit,
)

from capability_exchange.diagnosis.comparison import ComparisonLedger

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_wow_gate.py"


def _write_result(directory: Path, ledger: ComparisonLedger) -> Path:
    path = directory / "result.json"
    path.write_text(
        json.dumps({"ledger": ledger.model_dump(mode="json")}, default=str),
        encoding="utf-8",
    )
    return path


def _run(directory: Path, result: Path, *extra: str) -> tuple[int, dict[str, object], str]:
    output = directory / "grade.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--result", str(result), "--output", str(output), *extra],
        check=False,
        capture_output=True,
        text=True,
    )
    grade = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    return completed.returncode, grade, completed.stderr


def test_an_honest_run_passes_and_a_fabricated_one_does_not(tmp_path: Path) -> None:
    honest = tmp_path / "honest"
    honest.mkdir()
    code, grade, _ = _run(honest, _write_result(honest, _ledger(rich=True)))
    assert code == 0
    assert grade["passed"] is True
    assert grade["score"] >= 90

    invented = tmp_path / "invented"
    invented.mkdir()
    code, grade, _ = _run(invented, _write_result(invented, _fabricated_ledger()))
    assert code == 1
    assert grade["passed"] is False
    assert grade["score"] < 90


def test_a_failing_grade_names_what_failed(tmp_path: Path) -> None:
    """A hard-failure count alone cannot be acted on."""

    _, grade, _ = _run(tmp_path, _write_result(tmp_path, _fabricated_ledger()))
    assert grade["hard_failure_count"] >= 1
    assert "unsupported-claim" in grade["hard_failures"]


def test_it_refuses_another_runs_audit(tmp_path: Path) -> None:
    result = _write_result(tmp_path, _ledger(rich=True, audit=autonomous_audit()))
    stranger = tmp_path / "stranger-audit.json"
    stranger.write_text(
        json.dumps(_another_runs_audit().model_dump(mode="json"), default=str),
        encoding="utf-8",
    )

    code, _, stderr = _run(tmp_path, result, "--audit", str(stranger))

    assert code == 2
    assert "could not be graded" in stderr


def test_it_grades_without_a_separate_audit_file(tmp_path: Path) -> None:
    """The ledger carries its own audit, so the loop needs no hand-extraction."""

    code, grade, _ = _run(tmp_path, _write_result(tmp_path, _ledger(rich=True)))

    assert code == 0
    assert grade["dimensions"]["autonomy_and_clarity"] == 5


def test_the_written_grade_carries_nothing_from_the_inspected_system(tmp_path: Path) -> None:
    ledger = _ledger(rich=True)
    _, grade, _ = _run(tmp_path, _write_result(tmp_path, ledger))
    written = json.dumps(grade)

    for insight in (*ledger.strengths, *ledger.reciprocal_lessons):
        assert insight.explanation not in written
        assert insight.title not in written
    for item in ledger.ranked_recommendations:
        assert item.reason not in written
    for evidence in ledger.entries[0].evidence_references:
        assert evidence not in written


def test_an_unreadable_result_is_refused_without_repeating_it(tmp_path: Path) -> None:
    """A malformed file's own content is the inspected system's content."""

    canary = "INVENTED_SESSION_CANARY_NEVER_RETAIN"
    result = tmp_path / "result.json"
    result.write_text(json.dumps({"ledger": {"reciprocal_answer": canary}}), encoding="utf-8")

    code, _, stderr = _run(tmp_path, result)

    assert code == 2
    assert canary not in stderr
