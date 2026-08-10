"""Baseline/follow-up evidence templates for contract-specific P1 analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence.item import reference_rejection_reason
from capability_exchange.evidence.states import EvidenceState, coerce_state
from capability_exchange.pilot._common import clean_text, tuple_text, utc_now

__all__ = ["EvidenceRecord", "EvidenceTemplate", "MeasurementEvidence", "PilotEvidence"]


class MeasurementEvidence(InventoriedModel):
    """One bounded measurement, never raw inspected content."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    state: EvidenceState = EvidenceState.NOT_ASSESSED
    captured_at: datetime = Field(default_factory=utc_now)
    reference: str
    value: float | None = None
    objective_signal_observed: bool = False
    self_report_only: bool = False
    missing: bool = False
    improved: bool | None = None
    notes: str | None = None

    @field_validator("state", mode="before")
    @classmethod
    def _state(cls, value: object) -> EvidenceState:
        return coerce_state(value)

    @field_validator("captured_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("captured_at must be timezone-aware")
        return value

    @field_validator("reference")
    @classmethod
    def _reference(cls, value: str) -> str:
        value = clean_text(value, label="reference", max_length=512)
        reason = reference_rejection_reason(value)
        if reason is not None:
            raise ValueError(reason)
        return value

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, label="notes", max_length=512)

    @model_validator(mode="after")
    def _missing_state(self) -> Self:
        if self.missing and self.state in {
            EvidenceState.OBSERVED,
            EvidenceState.USER_REPORTED,
            EvidenceState.INFERRED,
        }:
            raise ValueError("missing evidence cannot claim a supporting state")
        if self.self_report_only and self.objective_signal_observed:
            raise ValueError("self-report-only evidence cannot claim an objective signal")
        return self


class EvidenceRecord(InventoriedModel):
    """A participant's baseline/follow-up pair for one Success Contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    participant_id: str
    contract_id: str
    baseline: MeasurementEvidence | None = None
    follow_up: MeasurementEvidence | None = None
    dropout: bool = False
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

    @model_validator(mode="after")
    def _failure_definition(self) -> Self:
        if self.severe_failure and not self.severe_failure_type:
            raise ValueError("severe_failure requires a named failure type")
        if self.dropout and self.follow_up is not None and not self.follow_up.missing:
            raise ValueError("a dropout cannot carry a complete follow-up measurement")
        return self

    @property
    def missing_follow_up(self) -> bool:
        return self.follow_up is None or self.follow_up.missing


# Friendly name used by pilot-facing callers and docs.
PilotEvidence = EvidenceRecord
EvidenceTemplate = MeasurementEvidence
