"""Contract-specific P1 analysis with a strict trust floor (G5/P1)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence.item import reference_rejection_reason
from capability_exchange.evidence.states import CLAIM_SUPPORTING_STATES, EvidenceState, coerce_state
from capability_exchange.pilot._common import clean_text, tuple_text
from capability_exchange.pilot.evidence import EvidenceRecord
from capability_exchange.pilot.measurement import (
    MeasurementPlan,
    MeasurementPlanError,
    strict_majority_threshold,
)

__all__ = [
    "AnalysisError",
    "ParticipantMeasurement",
    "ParticipantOutcome",
    "ParticipantResult",
    "PilotAnalysisReport",
    "AnalysisReport",
    "PilotVerdict",
    "analyze_pilot",
    "strict_majority_threshold",
]


class AnalysisError(MeasurementPlanError):
    """Input evidence cannot be evaluated without guessing or imputation."""


class PilotVerdict(StrEnum):
    SUCCESSFUL = "successful"
    NOT_DEMONSTRATED = "not demonstrated"
    STOP_AND_REVIEW = "stop-and-review"


class ParticipantMeasurement(InventoriedModel):
    """Normalized, private-free input row for one enrolled participant."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    participant_id: str
    contract_id: str
    stratum_id: str
    baseline_reference: str
    follow_up_reference: str | None = None
    baseline_value: float | None = None
    follow_up_value: float | None = None
    baseline_state: EvidenceState = EvidenceState.NOT_ASSESSED
    follow_up_state: EvidenceState = EvidenceState.NOT_ASSESSED
    baseline_objective_signal: bool = False
    follow_up_objective_signal: bool = False
    self_report_only: bool = False
    meaningful_improvement: bool | None = Field(default=None, alias="improved")
    dropout: bool = False
    missing_follow_up: bool = False
    severe_failure: bool = False
    severe_failure_type: str | None = None
    card_contribution_count: int = Field(default=0, ge=0)
    evidence_limits: tuple[str, ...] = ()
    baseline_captured_at: datetime | None = None
    follow_up_captured_at: datetime | None = None

    @field_validator("participant_id", "contract_id", "stratum_id")
    @classmethod
    def _id(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("baseline_reference", "follow_up_reference")
    @classmethod
    def _reference(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        value = clean_text(value, label=info.field_name, max_length=512)
        reason = reference_rejection_reason(value)
        if reason is not None:
            raise ValueError(reason)
        return value

    @field_validator("baseline_state", "follow_up_state", mode="before")
    @classmethod
    def _state(cls, value: object) -> EvidenceState:
        return coerce_state(value)

    @field_validator("severe_failure_type")
    @classmethod
    def _failure_type(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, label="severe_failure_type")

    @field_validator("evidence_limits")
    @classmethod
    def _limits(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple_text(value, label="evidence_limits")

    @field_validator("baseline_captured_at", "follow_up_captured_at")
    @classmethod
    def _aware(cls, value: datetime | None, info: Any) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _failure_type_required(self) -> Self:
        if self.severe_failure and not self.severe_failure_type:
            raise ValueError("severe_failure requires severe_failure_type")
        if not self.baseline_reference:
            raise ValueError("baseline_reference is required and must be non-raw")
        if not self.dropout and not self.missing_follow_up and not self.follow_up_reference:
            raise ValueError("follow_up_reference is required and must be non-raw")
        return self

    @classmethod
    def from_evidence(cls, evidence: EvidenceRecord) -> ParticipantMeasurement:
        baseline = evidence.baseline
        follow_up = evidence.follow_up
        limits = list(evidence.evidence_limits)
        if evidence.dropout:
            limits.append("dropout counts in enrolled denominator and is not-success")
        if follow_up is None or follow_up.missing:
            limits.append("missing follow-up is not imputed")
        if (baseline and baseline.self_report_only) or (follow_up and follow_up.self_report_only):
            limits.append("self-report-only evidence cannot satisfy an objective signal contract")
        return cls(
            participant_id=evidence.participant_id,
            contract_id=evidence.contract_id,
            stratum_id=evidence.stratum_id,
            baseline_reference=baseline.reference if baseline else "evidence://missing-baseline",
            follow_up_reference=follow_up.reference if follow_up else None,
            baseline_value=baseline.value if baseline else None,
            follow_up_value=follow_up.value if follow_up else None,
            baseline_state=baseline.state if baseline else EvidenceState.NOT_ASSESSED,
            follow_up_state=follow_up.state if follow_up else EvidenceState.NOT_ASSESSED,
            baseline_objective_signal=baseline.objective_signal_observed if baseline else False,
            follow_up_objective_signal=follow_up.objective_signal_observed if follow_up else False,
            self_report_only=(baseline.self_report_only if baseline else False)
            or (follow_up.self_report_only if follow_up else False),
            meaningful_improvement=follow_up.improved if follow_up else None,
            dropout=evidence.dropout,
            missing_follow_up=evidence.missing_follow_up,
            severe_failure=evidence.severe_failure,
            severe_failure_type=evidence.severe_failure_type,
            card_contribution_count=evidence.card_contribution_count,
            evidence_limits=tuple(limits),
            baseline_captured_at=baseline.captured_at if baseline else None,
            follow_up_captured_at=follow_up.captured_at if follow_up else None,
        )


class ParticipantResult(InventoriedModel):
    """Honest per-participant result; no aggregate or ranking fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    participant_id: str
    contract_id: str
    improved: bool = False
    counted_as_success: bool = False
    evidence_limited: bool = False
    dropout: bool = False
    missing_follow_up: bool = False
    severe_failure: bool = False
    severe_failure_type: str | None = None
    card_contribution_count: int = Field(default=0, ge=0)
    evidence_limits: tuple[str, ...] = ()

    @field_validator("participant_id", "contract_id")
    @classmethod
    def _id(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("severe_failure_type")
    @classmethod
    def _failure_type(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, label="severe_failure_type")

    @field_validator("evidence_limits")
    @classmethod
    def _limits(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple_text(value, label="evidence_limits")


class PilotAnalysisReport(InventoriedModel):
    """One contract's before/after report, explicitly formative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_id: str
    plan_hash: str
    enrolled_count: int = Field(ge=1)
    improved_count: int = Field(ge=0)
    improvement_threshold_count: int = Field(ge=1)
    verdict: PilotVerdict
    trust_floor_stop: bool = False
    review_required: bool = False
    participant_results: tuple[ParticipantResult, ...] = Field(min_length=1)
    evidence_limits: tuple[str, ...] = ()
    card_learning_count: int = Field(default=0, ge=0)
    formative_only: Literal[True] = True

    @field_validator("contract_id", "plan_hash")
    @classmethod
    def _id(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("evidence_limits")
    @classmethod
    def _limits(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple_text(value, label="evidence_limits")

    @model_validator(mode="after")
    def _counts(self) -> Self:
        if len(self.participant_results) != self.enrolled_count:
            raise ValueError("participant result count must equal enrolled denominator")
        if self.improved_count > self.enrolled_count:
            raise ValueError("improved_count cannot exceed enrolled_count")
        if self.verdict is PilotVerdict.SUCCESSFUL and self.trust_floor_stop:
            raise ValueError("a trust-floor stop cannot carry a successful verdict")
        return self

    @property
    def successful(self) -> bool:
        return self.verdict is PilotVerdict.SUCCESSFUL

    @property
    def not_successful(self) -> bool:
        return not self.successful

    @property
    def success_threshold(self) -> int:
        return self.improvement_threshold_count

    @property
    def success_count(self) -> int:
        return self.improved_count

    @property
    def status(self) -> str:
        """Human-facing compatibility label; verdict remains normative."""

        if self.verdict is PilotVerdict.STOP_AND_REVIEW:
            return "stop-and-review"
        if self.verdict is PilotVerdict.SUCCESSFUL:
            return "successful"
        return "not successful"


def _coerce_measurement(
    value: ParticipantMeasurement | EvidenceRecord | dict[str, Any],
) -> ParticipantMeasurement:
    if isinstance(value, ParticipantMeasurement):
        return value
    if isinstance(value, EvidenceRecord):
        return ParticipantMeasurement.from_evidence(value)
    if isinstance(value, dict):
        return ParticipantMeasurement.model_validate(value)
    raise AnalysisError("pilot evidence row is not a recognized measurement record")


def analyze_pilot(
    records: list[ParticipantMeasurement | EvidenceRecord | dict[str, Any]] | tuple[Any, ...],
    plan: MeasurementPlan,
    *,
    expected_participant_strata: dict[str, str],
    first_collection_at: datetime | None = None,
) -> PilotAnalysisReport:
    """Analyze one contract without imputation or aggregate/general claims."""

    measurements = tuple(_coerce_measurement(item) for item in records)
    if not measurements:
        raise AnalysisError("pilot analysis requires at least one enrolled participant")
    if len({item.participant_id for item in measurements}) != len(measurements):
        raise AnalysisError("duplicate participant ids would corrupt the enrolled denominator")
    if len(expected_participant_strata) < 6 or len(expected_participant_strata) > 8:
        raise AnalysisError("pilot analysis requires the complete 6–8 participant cohort")
    if {item.participant_id for item in measurements} != set(expected_participant_strata):
        raise AnalysisError(
            "analysis rows must match the exact enrolled participant set; "
            "dropouts and missing follow-up cannot be omitted"
        )
    if any(
        item.stratum_id != expected_participant_strata[item.participant_id]
        for item in measurements
    ):
        raise AnalysisError("analysis stratum does not match the enrolled participant roster")
    for stratum_id, (minimum, maximum) in plan.cohort_strata.items():
        count = sum(1 for item in measurements if item.stratum_id == stratum_id)
        if count < minimum or count > maximum:
            raise AnalysisError(
                f"analysis cohort stratum {stratum_id!r} has {count}; "
                f"locked quota is {minimum}–{maximum}"
            )
    undeclared = {item.stratum_id for item in measurements} - set(plan.cohort_strata)
    if undeclared:
        raise AnalysisError("analysis contains a stratum absent from the locked plan")
    if any(item.contract_id != plan.contract_id for item in measurements):
        raise AnalysisError("analysis is contract-specific; evidence contract id mismatched plan")
    try:
        plan.assert_admissible(first_collection_at=first_collection_at)
    except MeasurementPlanError as exc:
        raise AnalysisError(str(exc)) from exc

    results: list[ParticipantResult] = []
    improved_count = 0
    card_learning_count = 0
    report_limits: list[str] = []
    trust_floor_stop = False
    for item in measurements:
        limits = list(item.evidence_limits)
        improved = False
        evidence_limited = False
        if item.baseline_captured_at is None or not (
            plan.baseline_window.start
            <= item.baseline_captured_at
            <= plan.baseline_window.end
        ):
            raise AnalysisError(
                f"participant {item.participant_id} baseline is outside the locked baseline window"
            )
        if (
            item.baseline_captured_at < plan.locked_at  # type: ignore[operator]
            or item.baseline_captured_at < plan.first_data_collection_at
        ):
            raise AnalysisError(
                f"participant {item.participant_id} baseline predates the plan lock "
                "or first collection"
            )
        if not item.missing_follow_up and not item.dropout:
            if item.follow_up_captured_at is None or not (
                plan.follow_up_window.start
                <= item.follow_up_captured_at
                <= plan.follow_up_window.end
            ):
                raise AnalysisError(
                    f"participant {item.participant_id} follow-up is outside "
                    "the locked follow-up window"
                )
        if item.card_contribution_count:
            card_learning_count += item.card_contribution_count
        if item.severe_failure:
            trust_floor_stop = True
            limits.append(f"severe trust failure: {item.severe_failure_type or 'unspecified'}")
        elif item.dropout:
            evidence_limited = True
            limits.append("dropout remains in enrolled denominator and is not-success")
        elif item.missing_follow_up or item.follow_up_value is None:
            evidence_limited = True
            limits.append("missing follow-up is not imputed")
        elif item.self_report_only and plan.objective_signal_required:
            evidence_limited = True
            limits.append("self-report-only evidence is insufficient for an objective contract")
        elif (
            item.baseline_state not in CLAIM_SUPPORTING_STATES
            or item.follow_up_state not in CLAIM_SUPPORTING_STATES
        ):
            evidence_limited = True
            limits.append("baseline or follow-up evidence is not in a claim-supporting state")
        elif plan.objective_signal_required and not (
            item.baseline_objective_signal and item.follow_up_objective_signal
        ):
            evidence_limited = True
            limits.append("required objective/contemporaneous signal is missing")
        elif item.baseline_value is not None and item.follow_up_value is not None:
            computed_improvement = (
                item.follow_up_value - item.baseline_value
                >= plan.meaningful_improvement_threshold
            )
            if (
                item.meaningful_improvement is not None
                and item.meaningful_improvement != computed_improvement
            ):
                raise AnalysisError(
                    f"participant {item.participant_id} improvement claim "
                    "conflicts with locked threshold"
                )
            improved = computed_improvement
        else:
            evidence_limited = True
            limits.append("no measurable before/after values")

        if improved and not evidence_limited and not item.severe_failure:
            improved_count += 1
        if limits:
            report_limits.extend(f"{item.participant_id}: {limit}" for limit in limits)
        results.append(
            ParticipantResult(
                participant_id=item.participant_id,
                contract_id=item.contract_id,
                improved=bool(improved),
                counted_as_success=bool(
                    improved and not evidence_limited and not item.severe_failure
                ),
                evidence_limited=evidence_limited,
                dropout=item.dropout,
                missing_follow_up=item.missing_follow_up or item.follow_up_value is None,
                severe_failure=item.severe_failure,
                severe_failure_type=item.severe_failure_type,
                card_contribution_count=item.card_contribution_count,
                evidence_limits=tuple(limits),
            )
        )

    enrolled_count = len(results)
    threshold = plan.threshold_for(enrolled_count)
    verdict = (
        PilotVerdict.STOP_AND_REVIEW
        if trust_floor_stop
        else PilotVerdict.SUCCESSFUL
        if improved_count >= threshold
        else PilotVerdict.NOT_DEMONSTRATED
    )
    return PilotAnalysisReport(
        contract_id=plan.contract_id,
        plan_hash=plan.content_hash or "",
        enrolled_count=enrolled_count,
        improved_count=improved_count,
        improvement_threshold_count=threshold,
        verdict=verdict,
        trust_floor_stop=trust_floor_stop,
        review_required=trust_floor_stop,
        participant_results=tuple(results),
        evidence_limits=tuple(report_limits),
        card_learning_count=card_learning_count,
    )


ParticipantOutcome = ParticipantMeasurement
AnalysisReport = PilotAnalysisReport
