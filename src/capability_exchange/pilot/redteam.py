"""Synthetic R6 hostile-suite evidence and pilot-start gate."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.pilot._common import clean_text, content_hash

__all__ = [
    "REQUIRED_REDTEAM_GATES",
    "RedTeamCase",
    "RedTeamOutcome",
    "RedTeamReport",
    "evaluate_redteam",
]


REQUIRED_REDTEAM_GATES = ("G1", "G2", "G3", "G4", "R3")


class RedTeamOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_RUN = "not-run"


class RedTeamCase(InventoriedModel):
    """One observed hostile-suite result; synthetic only and commit-bound."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    gate: str
    test_id: str
    outcome: RedTeamOutcome = Field(alias="status")
    commit: str
    evidence_hash: str
    observed_at: datetime
    notes: str = ""

    @field_validator("gate", "test_id", "commit", "evidence_hash")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: str) -> str:
        return "" if not value else clean_text(value, label="notes", max_length=1024)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("observed_at must be timezone-aware")
        return value

    @property
    def passed(self) -> bool:
        return self.outcome is RedTeamOutcome.PASS


class RedTeamReport(InventoriedModel):
    """Machine-checkable R6 result, with no implied pass when cases are absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required_gates: tuple[str, ...] = REQUIRED_REDTEAM_GATES
    cases: tuple[RedTeamCase, ...] = ()
    synthetic_system: bool = True
    commit: str | None = None
    content_hash: str | None = None
    pilot_start_allowed: bool = False
    guided_downgrade_available: bool = False
    explanation: str

    @field_validator("required_gates")
    @classmethod
    def _required(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(value) != REQUIRED_REDTEAM_GATES:
            raise ValueError("R6 required red-team gates are G1, G2, G3, G4, and R3")
        return value

    @field_validator("commit")
    @classmethod
    def _commit(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, label="commit", max_length=128)

    @field_validator("explanation")
    @classmethod
    def _explanation(cls, value: str) -> str:
        return clean_text(value, label="explanation", max_length=1024)

    @model_validator(mode="after")
    def _state(self) -> Self:
        if self.content_hash is not None and self.content_hash != self.canonical_hash():
            raise ValueError("red-team report content hash does not match cases")
        if self.content_hash is None:
            object.__setattr__(self, "content_hash", self.canonical_hash())
        # A report can never claim pilot start if any required gate is absent,
        # not-run, failed, or if cases disagree on commit.
        by_gate: dict[str, list[RedTeamCase]] = {gate: [] for gate in self.required_gates}
        for case in self.cases:
            if case.gate in by_gate:
                by_gate[case.gate].append(case)
        complete = all(
            cases and all(case.outcome is RedTeamOutcome.PASS for case in cases)
            for cases in by_gate.values()
        )
        commits = {case.commit for case in self.cases}
        if len(commits) > 1:
            complete = False
        if self.pilot_start_allowed and not complete:
            raise ValueError("red-team report cannot claim pilot_start_allowed without all passes")
        if self.guided_downgrade_available:
            g1_ok = by_gate["G1"] and all(case.passed for case in by_gate["G1"])
            others_ok = all(
                by_gate[gate] and all(case.passed for case in by_gate[gate])
                for gate in self.required_gates
                if gate != "G1"
            )
            if g1_ok or not others_ok:
                raise ValueError("guided downgrade is permitted only when G1 alone is unproven")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def canonical_hash(self) -> str:
        return content_hash(self.canonical_payload())

    @property
    def complete(self) -> bool:
        return self.pilot_start_allowed


def evaluate_redteam(
    cases: tuple[RedTeamCase, ...] | list[RedTeamCase],
    *,
    commit: str | None = None,
    observed_at: datetime | None = None,
) -> RedTeamReport:
    """Evaluate supplied observed results; missing cases remain not-run.

    This function does not run tests and never invents a pass.  Callers attach
    actual fixture outcomes and a commit from the exact pilot build.
    """

    case_tuple = tuple(cases)
    commits = {case.commit for case in case_tuple}
    chosen_commit = commit or (next(iter(commits)) if len(commits) == 1 else None)
    if chosen_commit is not None and any(case.commit != chosen_commit for case in case_tuple):
        chosen_commit = None
    by_gate = {gate: [] for gate in REQUIRED_REDTEAM_GATES}
    for case in case_tuple:
        if case.gate in by_gate:
            by_gate[case.gate].append(case)
    all_pass = all(
        by_gate[gate] and all(case.outcome is RedTeamOutcome.PASS for case in by_gate[gate])
        for gate in REQUIRED_REDTEAM_GATES
    )
    g1_failed = not by_gate["G1"] or any(
        case.outcome is not RedTeamOutcome.PASS for case in by_gate["G1"]
    )
    others_pass = all(
        by_gate[gate] and all(case.outcome is RedTeamOutcome.PASS for case in by_gate[gate])
        for gate in REQUIRED_REDTEAM_GATES
        if gate != "G1"
    )
    downgrade = g1_failed and others_pass
    explanation = (
        "all required hostile suites passed against one exact synthetic commit"
        if all_pass
        else "G1 alone is unproven; guided/export-assisted collection is the only downgrade"
        if downgrade
        else "missing or failing hostile evidence blocks pilot start"
    )
    return RedTeamReport(
        cases=case_tuple,
        commit=chosen_commit,
        pilot_start_allowed=all_pass,
        guided_downgrade_available=downgrade,
        explanation=explanation,
    )
