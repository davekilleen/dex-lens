"""SuccessContract schema tests (M-C; gates.md R1; M2 #351/#352 criteria)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from capability_exchange.jobs import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


def make_boundaries() -> JobBoundaries:
    return JobBoundaries(
        privacy_limits=("never read the personal journal folder",),
        approval_limits=("sending anything anywhere needs fresh approval",),
        autonomy_limits=("no autonomous change of any file",),
    )


def make_contract(**overrides: object) -> SuccessContract:
    values: dict[str, object] = {
        "job_id": "weekly-report-prep",
        "situation": "Every Friday a report has to go out",
        "desired_outcome": "The report is ready by Friday noon",
        "success_evidence": ("the report exists before noon on Friday",),
        "boundaries": make_boundaries(),
        "importance": JobImportance.HIGH,
        "cadence": JobCadence.WEEKLY,
        "confirmed_at": NOW,
    }
    values.update(overrides)
    return SuccessContract(**values)  # type: ignore[arg-type]


class TestContractSchema:
    def test_contract_carries_the_full_schema(self) -> None:
        contract = make_contract()
        assert contract.situation
        assert contract.desired_outcome
        assert contract.success_evidence
        assert contract.boundaries.privacy_limits
        assert contract.boundaries.approval_limits
        assert contract.boundaries.autonomy_limits
        assert contract.importance is JobImportance.HIGH
        assert contract.cadence is JobCadence.WEEKLY
        assert contract.confirmed_at == NOW

    def test_lifecycle_is_machine_readably_diagnosis(self) -> None:
        assert make_contract().lifecycle == "diagnosis"

    def test_lifecycle_admits_no_other_value(self) -> None:
        with pytest.raises(ValidationError):
            make_contract(lifecycle="inspection")

    def test_contract_is_frozen(self) -> None:
        contract = make_contract()
        with pytest.raises(ValidationError):
            contract.situation = "rewritten"  # type: ignore[misc]

    def test_success_evidence_requires_at_least_one_signal(self) -> None:
        with pytest.raises(ValidationError):
            make_contract(success_evidence=())

    def test_naive_confirmation_timestamp_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_contract(confirmed_at=datetime(2026, 8, 7, 12, 0, 0))

    @pytest.mark.parametrize("bad_id", ["Weekly", "weekly_report", "-weekly", ""])
    def test_job_id_must_be_kebab_case(self, bad_id: str) -> None:
        with pytest.raises(ValidationError):
            make_contract(job_id=bad_id)

    def test_boundary_limits_are_bounded_single_lines(self) -> None:
        with pytest.raises(ValidationError):
            JobBoundaries(
                privacy_limits=("line one\nline two",),
                approval_limits=(),
                autonomy_limits=(),
            )
        with pytest.raises(ValidationError):
            JobBoundaries(
                privacy_limits=("x" * 513,),
                approval_limits=(),
                autonomy_limits=(),
            )

    def test_all_three_boundary_axes_are_required(self) -> None:
        with pytest.raises(ValidationError):
            JobBoundaries(privacy_limits=(), approval_limits=())  # type: ignore[call-arg]


class TestClosedVocabularies:
    def test_importance_is_a_closed_vocabulary(self) -> None:
        with pytest.raises(ValidationError):
            make_contract(importance="critical")

    def test_cadence_is_a_closed_vocabulary(self) -> None:
        with pytest.raises(ValidationError):
            make_contract(cadence="hourly")


class TestNoAggregateScoreIsRepresentable:
    """M2 criterion: no aggregate score / rank field in any schema.

    Schema test, not code review: extra fields are forbidden, so nobody can
    attach a score to a contract or its boundaries.
    """

    @pytest.mark.parametrize(
        "smuggled",
        [
            {"aggregate_score": 0.9},
            {"maturity_rank": 3},
            {"resemblance_percentage": 87},
            {"score": 1},
        ],
    )
    def test_score_shaped_fields_are_unrepresentable(self, smuggled: dict) -> None:
        with pytest.raises(ValidationError):
            make_contract(**smuggled)

    def test_no_field_of_the_schema_is_score_shaped(self) -> None:
        for field_name in SuccessContract.model_fields:
            lowered = field_name.lower()
            for banned in ("score", "rank", "percent", "grade", "rating"):
                assert banned not in lowered


class TestValidationBypassRoutes:
    """The ``diagnosis`` lifecycle literal must hold on the validation-skip
    routes too (R1; mirrors InspectionJob's own guards)."""

    def test_model_construct_cannot_forge_a_lifecycle(self) -> None:
        values = dict(make_contract())
        values["lifecycle"] = "inspection"
        with pytest.raises(ValueError, match="lifecycle"):
            SuccessContract.model_construct(**values)

    def test_model_copy_cannot_swap_the_lifecycle(self) -> None:
        with pytest.raises(ValueError, match="lifecycle"):
            make_contract().model_copy(update={"lifecycle": "inspection"})

    def test_model_construct_accepts_a_confirmed_contract(self) -> None:
        rebuilt = SuccessContract.model_construct(**dict(make_contract()))
        assert rebuilt.lifecycle == "diagnosis"
