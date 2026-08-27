from __future__ import annotations

import json
import sys
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from tests.evals.real_session_fixture import (
    CANARY,
    EXPECTED_COUNTS,
    NOW,
    real_session_fingerprint,
    real_session_input,
    real_session_ledger,
    real_session_report,
    synthetic_entry_ids,
)

from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.orchestrator import VerifiedCatalogueSlice
from capability_exchange.evaluation.diagnosis import evaluate_diagnosis
from capability_exchange.evaluation.replay import (
    FIXED_RUN_ID,
    ReplayBundle,
    ReplayHarness,
    run_direct,
)

EXPECTED = Path(__file__).parents[1] / "fixtures" / "evals" / "real-session-expected.json"
FALSE_COVERAGE_CLAIM = "93 capabilities are already covered"


class StrictExpectedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ExpectedObservationCounts(StrictExpectedModel):
    mcp_servers_declared: Literal[0]
    mcp_tools_known: Literal[0]
    automation_implemented: Literal[0]
    automation_loaded: Literal[0]
    health_collectors: Literal[0]
    restore_proofs: Literal[0]


class ExpectedDispositionCounts(StrictExpectedModel):
    not_assessed: Literal[80] = Field(alias=Disposition.NOT_ASSESSED.value)
    not_relevant: Literal[17] = Field(alias=Disposition.NOT_RELEVANT.value)
    shared: Literal[8]
    worth_borrowing: Literal[3] = Field(alias=Disposition.WORTH_BORROWING.value)
    fragile_or_contradictory: Literal[3] = Field(alias=Disposition.FRAGILE_OR_CONTRADICTORY.value)
    strong_here: Literal[2] = Field(alias=Disposition.STRONG_HERE.value)
    dex_should_learn: Literal[2] = Field(alias=Disposition.DEX_SHOULD_LEARN.value)


class ExpectedStage(StrEnum):
    CREATED = "created"
    SCOPE_APPROVED = "scope-approved"
    CAPTURED = "captured"
    CATALOGUE_VERIFIED = "catalogue-verified"
    JOBS_CONFIRMED = "jobs-confirmed"
    COMPARED = "compared"
    RENDERED = "rendered"
    CHECKED = "checked"
    SAVED = "saved"
    CLOSED = "closed"


class ExpectedProvenanceClass(StrEnum):
    VAULT_AUTHORED = "vault-authored"
    USER_GLOBAL = "user-global"


class ExpectedCleanCloseField(StrEnum):
    STRONGEST_GROUNDED_CAPABILITY = "strongest_grounded_capability"
    RECIPROCAL_VALUE = "reciprocal_value"
    SINGLE_BEST_FIRST_MOVE = "single_best_first_move"
    REPORT_LOCATION = "report_location"
    RETURN_TO_RUN = "return_to_run"
    SHARING_CHOICE = "sharing_choice"
    FUTURE_WATCH_CHOICE = "future_watch_choice"


class RealSessionExpectedContract(StrictExpectedModel):
    release_id: Literal["invented-release-v1"]
    observations: ExpectedObservationCounts
    catalogue_entry_count: Literal[115]
    disposition_counts: ExpectedDispositionCounts
    expected_stage_order: tuple[ExpectedStage, ...]
    forbidden_claims: tuple[Literal["93 capabilities are already covered"], ...]
    required_provenance_classes: tuple[ExpectedProvenanceClass, ...]
    required_clean_close_fields: tuple[ExpectedCleanCloseField, ...]
    max_recommendations: Literal[3]
    requires_strength: Literal[True]
    requires_reciprocal_answer: Literal[True]

    @field_validator("expected_stage_order")
    @classmethod
    def _stage_order_is_exact(cls, value: tuple[ExpectedStage, ...]) -> tuple[ExpectedStage, ...]:
        if value != tuple(ExpectedStage):
            raise ValueError("expected_stage_order must contain every stage in exact order")
        return value

    @field_validator("required_provenance_classes")
    @classmethod
    def _provenance_classes_are_exact(
        cls, value: tuple[ExpectedProvenanceClass, ...]
    ) -> tuple[ExpectedProvenanceClass, ...]:
        if value != tuple(ExpectedProvenanceClass):
            raise ValueError(
                "required_provenance_classes must contain both source classes in exact order"
            )
        return value

    @field_validator("required_clean_close_fields")
    @classmethod
    def _clean_close_fields_are_exact(
        cls, value: tuple[ExpectedCleanCloseField, ...]
    ) -> tuple[ExpectedCleanCloseField, ...]:
        if value != tuple(ExpectedCleanCloseField):
            raise ValueError(
                "required_clean_close_fields must contain every clean-close field in exact order"
            )
        return value

    def evaluator_mapping(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)

    def without_literal_blacklist(self) -> Self:
        raw = self.evaluator_mapping()
        raw["forbidden_claims"] = []
        return self.model_validate_json(json.dumps(raw))


def expected_contract() -> RealSessionExpectedContract:
    return RealSessionExpectedContract.model_validate_json(EXPECTED.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("case", "error_field"),
    (
        ("missing-required-field", "catalogue_entry_count"),
        ("extra-top-level-field", "unexpected_field"),
        ("malformed-disposition-count", "not-assessed"),
        ("extra-nested-disposition", "invented-extra"),
        ("unknown-stage", "expected_stage_order"),
    ),
)
def test_expected_contract_rejects_malformed_mapping(
    case: str,
    error_field: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if case == "missing-required-field":
        raw.pop("catalogue_entry_count")
    elif case == "extra-top-level-field":
        raw["unexpected_field"] = "invented"
    elif case == "malformed-disposition-count":
        raw["disposition_counts"]["not-assessed"] = "eighty"
    elif case == "extra-nested-disposition":
        raw["disposition_counts"]["invented-extra"] = 1
    else:
        raw["expected_stage_order"][0] = "finished"

    malformed = tmp_path / f"{case}.json"
    malformed.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "EXPECTED", malformed)

    with pytest.raises(ValidationError, match=error_field):
        expected_contract()


def test_report_cannot_claim_93_covered_when_80_are_not_assessed() -> None:
    ledger = real_session_ledger()
    truthful_report = real_session_report()
    contradictory_report = truthful_report.replace(
        "80 capabilities remain Unknown",
        FALSE_COVERAGE_CLAIM,
    )
    expected = expected_contract()
    expected_mapping = expected.evaluator_mapping()

    assert synthetic_entry_ids() == tuple(
        f"invented-capability-{index:03d}" for index in range(115)
    )
    assert Counter(item.disposition for item in ledger.entries) == EXPECTED_COUNTS
    assert expected.catalogue_entry_count == len(ledger.entries)
    assert expected.disposition_counts.model_dump(mode="json", by_alias=True) == {
        disposition.value: count for disposition, count in EXPECTED_COUNTS.items()
    }
    assert {item.source_class for item in real_session_input().sources} == set(
        expected.required_provenance_classes
    )
    assert expected.forbidden_claims == (FALSE_COVERAGE_CLAIM,)
    assert len({item.name for item in real_session_input().sources}) == 1
    assert all(
        reference.startswith(("probe-token:", "file-token:"))
        for item in ledger.entries
        for reference in item.evidence_references
    )
    assert all(
        item.evidence.reference.startswith(("probe-token:", "file-token:"))
        for item in real_session_fingerprint().observations
    )
    retained = "\n".join(
        (
            real_session_fingerprint().model_dump_json(),
            ledger.model_dump_json(),
            contradictory_report,
            expected.model_dump_json(by_alias=True),
        )
    )
    assert CANARY not in retained

    truthful_result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=truthful_report,
        expected=expected_mapping,
    )
    assert truthful_result.passed, truthful_result

    reconciliation_contract = expected.without_literal_blacklist()
    result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=contradictory_report,
        expected=reconciliation_contract.evaluator_mapping(),
    )

    assert not result.passed, (
        "contradictory coverage report passed because the evaluator did not "
        "reconcile ledger-derived facts"
    )
    assert any("ledger-derived facts" in item for item in result.report_errors), (
        result.report_errors
    )


def _order(items: tuple[object, ...], ordering: str) -> tuple[object, ...]:
    if ordering == "forward":
        return items
    if ordering == "reverse":
        return tuple(reversed(items))
    if ordering == "rotated":
        if not items:
            return items
        return items[1:] + items[:1]
    raise ValueError(f"unknown replay ordering: {ordering}")


def real_session_replay(*, ordering: str = "forward") -> ReplayBundle:
    """Sanitised real-session input with a fixed clock and run id."""

    fingerprint = real_session_fingerprint()
    fingerprint = fingerprint.model_copy(
        update={"observations": _order(fingerprint.observations, ordering)}
    )
    ledger = real_session_ledger()
    ledger = ledger.model_copy(
        update={
            "capabilities": _order(ledger.capabilities, ordering),
            "entries": _order(ledger.entries, ordering),
        }
    )
    return ReplayBundle(
        fingerprint=fingerprint,
        catalogue=VerifiedCatalogueSlice(
            version=ledger.catalogue_version,
            sha256=ledger.catalogue_sha256,
            catalogue_ids=tuple(item.catalogue_id for item in ledger.entries),
            capability_ids=tuple(item.capability_id for item in ledger.capabilities),
            unavailable_ids=(),
            family_contract_present=False,
        ),
        ledger=ledger,
        proposals=(),
        clock=NOW,
        run_id=FIXED_RUN_ID,
    )


def test_engine_replay_never_retains_the_session_canary(tmp_path: Path) -> None:
    replay = real_session_replay(ordering="forward")
    harness = ReplayHarness(replay, tmp_path)
    result = harness.run_to_closed()
    retained = "\n".join(
        (
            harness.retained_text(),
            result.dump_for_storage().__repr__(),
            json.dumps(result.dump_for_storage(), default=str),
            run_direct(replay).decode("utf-8"),
        )
    )
    assert CANARY not in retained
    assert replay.fingerprint.model_dump_json().find(CANARY) == -1
