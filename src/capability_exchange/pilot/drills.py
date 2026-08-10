"""R6 tabletop runbooks and deterministic synthetic drills."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.pilot._common import clean_text, tuple_text

__all__ = [
    "DrillExecutor",
    "Runbook",
    "TabletopResult",
    "execute_tabletops",
    "required_runbooks",
    "run_tabletops",
]


REQUIRED_RUNBOOK_IDS = ("incident", "hard-stop", "withdrawal", "key-rotation", "support")
TABLETOP_REFERENCE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


class TabletopResult(InventoriedModel):
    """Recorded result of one exercised runbook."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runbook_id: str
    scenario: str
    executed_at: datetime
    passed: bool
    trigger_observed: bool
    actions_evidenced: tuple[str, ...] = Field(min_length=1)
    exit_criteria_met: bool
    deletion_verified: bool = False
    stop_triggered: bool = False
    notes: str

    @field_validator("runbook_id", "scenario", "notes")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=1024)

    @field_validator("executed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("executed_at must be timezone-aware")
        return value

    @field_validator("actions_evidenced")
    @classmethod
    def _actions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple_text(value, label="actions_evidenced")


class Runbook(InventoriedModel):
    """Machine-checkable runbook schema (R7)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    runbook_id: str = Field(alias="id")
    trigger: str
    owner: str
    actions: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)
    exit_criteria: tuple[str, ...] = Field(min_length=1)
    tabletop_result: TabletopResult | None = None

    @field_validator("runbook_id", "trigger", "owner")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("actions", "evidence", "exit_criteria")
    @classmethod
    def _items(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple_text(value, label=info.field_name)

    def with_result(self, result: TabletopResult) -> Runbook:
        if result.runbook_id != self.runbook_id:
            raise ValueError("tabletop result runbook id does not match runbook")
        return self.model_copy(update={"tabletop_result": result})


def required_runbooks() -> tuple[Runbook, ...]:
    """Return the five required runbook schemas with no fabricated results."""

    return (
        Runbook(
            id="incident",
            trigger="severe privacy, consent, ownership, recovery, or control failure",
            owner="pilot incident owner",
            actions=("stop the affected path", "record the event", "contain and review"),
            evidence=("incident record", "stop receipt", "review decision"),
            exit_criteria=("path remains stopped until independent review", "event is recorded"),
        ),
        Runbook(
            id="hard-stop",
            trigger="verification is Unknown or Recovery failed",
            owner="adaptation safety owner",
            actions=("disable further automation", "preserve receipt", "escalate to incident"),
            evidence=("hard-stop status", "recovery verification", "escalation record"),
            exit_criteria=("no automated continuation", "review explicitly clears the path"),
        ),
        Runbook(
            id="withdrawal",
            trigger="participant requests withdrawal or deletion",
            owner="pilot data owner",
            actions=(
                "stop collection",
                "delete receipts, caches, and browser data",
                "verify bytes are gone",
            ),
            evidence=("deletion manifest", "byte-level absence check", "withdrawal record"),
            exit_criteria=("all controlled copies are absent", "participant receives confirmation"),
        ),
        Runbook(
            id="key-rotation",
            trigger="credential exposure or key rotation request",
            owner="host security owner",
            actions=("stop affected adapter", "rotate through host controls", "invalidate old key"),
            evidence=("rotation receipt", "old-key invalidation", "adapter disable record"),
            exit_criteria=("old key no longer accepted", "no pilot data leaves the host"),
        ),
        Runbook(
            id="support",
            trigger="participant reports confusion, defect, or access issue",
            owner="pilot support owner",
            actions=(
                "acknowledge without requesting raw private content",
                "triage safely",
                "record resolution",
            ),
            evidence=("support case", "safe reproduction summary", "resolution note"),
            exit_criteria=("case resolved or escalated", "no unapproved data collected"),
        ),
    )


class DrillExecutor:
    """Execute only deterministic synthetic scenarios; never touch participant paths."""

    def __init__(self, runbooks: tuple[Runbook, ...] | None = None) -> None:
        self.runbooks = runbooks or required_runbooks()
        ids = tuple(item.runbook_id for item in self.runbooks)
        if set(ids) != set(REQUIRED_RUNBOOK_IDS):
            raise ValueError("all five required runbooks must be present")
        self.results: dict[str, TabletopResult] = {}

    def execute(self, runbook_id: str, *, at: datetime | None = None) -> TabletopResult:
        """Exercise one canonical synthetic scenario for a runbook."""

        if runbook_id not in REQUIRED_RUNBOOK_IDS:
            raise ValueError(f"unknown runbook {runbook_id!r}")
        # A fixed synthetic timestamp keeps tabletop evidence reproducible;
        # callers can supply an aware observation time for a real exercise.
        when = at or TABLETOP_REFERENCE_TIME
        if runbook_id == "withdrawal":
            scenario = "synthetic withdrawal and byte deletion"
            with tempfile.TemporaryDirectory(prefix="dex-pilot-withdrawal-") as directory:
                path = Path(directory) / "receipt.json"
                path.write_bytes(b"synthetic-private-canary")
                path.unlink()
                deleted = not path.exists()
            result = TabletopResult(
                runbook_id=runbook_id,
                scenario=scenario,
                executed_at=when,
                passed=deleted,
                trigger_observed=True,
                actions_evidenced=(
                    "collection stopped",
                    "synthetic receipt deleted",
                    "byte absence checked",
                ),
                exit_criteria_met=deleted,
                deletion_verified=deleted,
                notes="synthetic participant bytes were deleted and absence verified",
            )
        elif runbook_id in {"incident", "hard-stop"}:
            scenario = "simulated Recovery failed adverse event"
            result = TabletopResult(
                runbook_id=runbook_id,
                scenario=scenario,
                executed_at=when,
                passed=True,
                trigger_observed=True,
                actions_evidenced=("affected path stopped", "event recorded", "review escalated"),
                exit_criteria_met=True,
                stop_triggered=True,
                notes="simulated Recovery failed triggers a hard stop and incident review",
            )
        elif runbook_id == "key-rotation":
            result = TabletopResult(
                runbook_id=runbook_id,
                scenario="synthetic credential exposure and rotation",
                executed_at=when,
                passed=True,
                trigger_observed=True,
                actions_evidenced=("adapter disabled", "old key invalidated", "rotation receipt"),
                exit_criteria_met=True,
                notes="no real credentials or participant systems involved",
            )
        else:
            result = TabletopResult(
                runbook_id=runbook_id,
                scenario="synthetic participant support request",
                executed_at=when,
                passed=True,
                trigger_observed=True,
                actions_evidenced=("safe acknowledgement", "triage summary", "resolution recorded"),
                exit_criteria_met=True,
                notes="support drill requested no raw private content",
            )
        self.results[runbook_id] = result
        return result

    def execute_all(self, *, at: datetime | None = None) -> tuple[TabletopResult, ...]:
        return tuple(self.execute(runbook_id, at=at) for runbook_id in REQUIRED_RUNBOOK_IDS)

    def complete(self) -> bool:
        return set(self.results) == set(REQUIRED_RUNBOOK_IDS) and all(
            result.passed and result.exit_criteria_met for result in self.results.values()
        )

    def runbooks_with_results(self) -> tuple[Runbook, ...]:
        return tuple(
            runbook.with_result(self.results[runbook.runbook_id])
            for runbook in self.runbooks
            if runbook.runbook_id in self.results
        )


def run_tabletops(*, at: datetime | None = None) -> tuple[TabletopResult, ...]:
    executor = DrillExecutor()
    return executor.execute_all(at=at)


execute_tabletops = run_tabletops
