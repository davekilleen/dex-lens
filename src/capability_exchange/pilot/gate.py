"""Exact-build release gate for all six Fable gates plus R3."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.pilot._common import clean_text, content_hash

__all__ = [
    "PILOT_GATE_TESTS",
    "REQUIRED_PILOT_GATES",
    "GateRun",
    "PilotBuildGateReport",
    "PilotGateEvidence",
    "PilotGateOutcome",
    "execute_pilot_gate",
    "subprocess_gate_runner",
]

REQUIRED_PILOT_GATES: Final = ("G1", "G2", "G3", "G4", "G5", "G6", "R3")
_SIX_FABLE_GATES: Final = frozenset({"G1", "G2", "G3", "G4", "G5", "G6"})
_R6_REDTEAM_GATES: Final = frozenset({"G1", "G2", "G3", "G4", "R3"})
_SHA = re.compile(r"^[0-9a-f]{40}$")

PILOT_GATE_TESTS: Final = MappingProxyType(
    {
        "G1": (
            "tests/adapters/claude_code/test_containment.py",
            "tests/fixtures/hostile/test_g1_external_model_requests.py",
            "tests/fixtures/hostile/test_g1_mutation_during_inspection.py",
            "tests/fixtures/hostile/test_g1_planted_secrets.py",
            "tests/fixtures/hostile/test_g1_prompt_injection.py",
            "tests/fixtures/hostile/test_g1_symlink_hardlink_escapes.py",
        ),
        "G2": (
            "tests/boundary",
            "tests/egress",
        ),
        "G3": (
            "tests/adaptation",
            "tests/fixtures/hostile/test_g3_adaptation.py",
        ),
        "G4": (
            "tests/cards",
            "tests/catalog",
            "tests/contribution",
        ),
        "G5": (
            "tests/pilot/test_measurement_lock.py",
            "tests/pilot/test_analysis_hostile.py",
            "tests/pilot/test_drills.py",
        ),
        "G6": (
            "tests/taxonomy",
            "tests/adaptation/test_eligibility.py",
        ),
        "R3": (
            "tests/concierge/test_r3_security.py",
            "tests/concierge/test_r3_collection.py",
            "tests/concierge/test_local_server.py",
        ),
    }
)


class PilotGateOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class GateRun:
    exit_code: int
    output: str


class PilotGateEvidence(InventoriedModel):
    """One executed gate result, bound to exact tests and build commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: str
    test_ids: tuple[str, ...] = Field(min_length=1)
    outcome: PilotGateOutcome
    commit: str
    output_sha256: str
    exit_code: int
    observed_at: datetime

    @field_validator("gate", "commit", "output_sha256")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value


class PilotBuildGateReport(InventoriedModel):
    """Release-blocking exact-build verdict; no missing evidence can pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    commit: str
    evidence: tuple[PilotGateEvidence, ...] = Field(min_length=1)
    exact_build_verified: bool
    all_six_gates_green: bool
    r6_redteam_green: bool
    pilot_start_allowed: bool
    guided_downgrade_available: bool
    explanation: str
    content_hash: str | None = None

    @field_validator("commit", "explanation")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=1024)

    @model_validator(mode="after")
    def _closed_verdict(self) -> Self:
        if not _SHA.fullmatch(self.commit):
            raise ValueError("commit must be an exact lowercase 40-character Git SHA")
        by_gate = {item.gate: item for item in self.evidence}
        exact = (
            tuple(item.gate for item in self.evidence) == REQUIRED_PILOT_GATES
            and all(item.commit == self.commit for item in self.evidence)
            and all(item.test_ids == PILOT_GATE_TESTS[item.gate] for item in self.evidence)
        )
        passes = {
            gate
            for gate, item in by_gate.items()
            if item.outcome is PilotGateOutcome.PASS and item.exit_code == 0
        }
        six_green = _SIX_FABLE_GATES <= passes
        redteam_green = _R6_REDTEAM_GATES <= passes
        allowed = exact and six_green and redteam_green and "R3" in passes
        guided = (
            exact
            and "G1" not in passes
            and (set(REQUIRED_PILOT_GATES) - {"G1"}) <= passes
        )
        claimed = (
            self.exact_build_verified,
            self.all_six_gates_green,
            self.r6_redteam_green,
            self.pilot_start_allowed,
            self.guided_downgrade_available,
        )
        derived = (exact, six_green, redteam_green, allowed, guided)
        if claimed != derived:
            raise ValueError("pilot gate verdict fields do not match executable evidence")
        expected_hash = self.canonical_hash()
        if self.content_hash is not None and self.content_hash != expected_hash:
            raise ValueError("pilot gate content_hash does not match exact evidence")
        if self.content_hash is None:
            object.__setattr__(self, "content_hash", expected_hash)
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def canonical_hash(self) -> str:
        return content_hash(self.canonical_payload())


GateRunner = Callable[[tuple[str, ...]], GateRun]


def subprocess_gate_runner(test_ids: tuple[str, ...]) -> GateRun:
    """Run real pytest node paths without a shell or declared-pass shortcut."""

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *test_ids],
        check=False,
        capture_output=True,
        text=True,
    )
    return GateRun(
        exit_code=completed.returncode,
        output=f"{completed.stdout}\n{completed.stderr}",
    )


def execute_pilot_gate(
    *,
    commit: str,
    observed_at: datetime,
    runner: GateRunner = subprocess_gate_runner,
) -> PilotBuildGateReport:
    """Execute every named gate and derive the only permitted pilot verdict."""

    if not _SHA.fullmatch(commit):
        raise ValueError("commit must be an exact lowercase 40-character Git SHA")
    evidence: list[PilotGateEvidence] = []
    for gate, test_ids in PILOT_GATE_TESTS.items():
        try:
            run = runner(test_ids)
            outcome = PilotGateOutcome.PASS if run.exit_code == 0 else PilotGateOutcome.FAIL
            output = run.output
            exit_code = run.exit_code
        except Exception as exc:  # noqa: BLE001 - tool failure is gate failure
            outcome = PilotGateOutcome.ERROR
            output = f"{type(exc).__name__}: {exc}"
            exit_code = -1
        evidence.append(
            PilotGateEvidence(
                gate=gate,
                test_ids=test_ids,
                outcome=outcome,
                commit=commit,
                output_sha256=hashlib.sha256(output.encode("utf-8")).hexdigest(),
                exit_code=exit_code,
                observed_at=observed_at,
            )
        )
    passed = {
        item.gate
        for item in evidence
        if item.outcome is PilotGateOutcome.PASS and item.exit_code == 0
    }
    six_green = _SIX_FABLE_GATES <= passed
    redteam_green = _R6_REDTEAM_GATES <= passed
    guided = "G1" not in passed and (set(REQUIRED_PILOT_GATES) - {"G1"}) <= passed
    allowed = six_green and redteam_green and "R3" in passed
    explanation = (
        "all six Fable gates and R3 passed on the exact pilot build"
        if allowed
        else "G1 alone is unproven; guided/export-assisted collection is the only downgrade"
        if guided
        else "missing or failing exact-build gate evidence blocks pilot start"
    )
    return PilotBuildGateReport(
        commit=commit,
        evidence=tuple(evidence),
        exact_build_verified=True,
        all_six_gates_green=six_green,
        r6_redteam_green=redteam_green,
        pilot_start_allowed=allowed,
        guided_downgrade_available=guided,
        explanation=explanation,
    )
