"""Hash-locked, contract-specific pilot measurement plans (G5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.pilot._common import clean_text, content_hash, utc_now

__all__ = [
    "LockedMeasurementPlan",
    "MeasurementPlan",
    "MeasurementPlanTemplate",
    "MeasurementPlanError",
    "MeasurementWindow",
    "canonical_plan_hash",
    "strict_majority_table",
    "strict_majority_threshold",
]


class MeasurementPlanError(ValueError):
    """A plan is absent, unlocked, edited, or temporally inadmissible."""


class MeasurementWindow(InventoriedModel):
    """Inclusive UTC window for baseline or follow-up collection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, value: datetime, info: Any) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(f"measurement window {info.field_name} must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("measurement window end must be on or after start")
        return self


_STRICT_MAJORITY: dict[int, int] = {6: 4, 7: 4, 8: 5}


def strict_majority_threshold(enrolled_count: int) -> int:
    """Pinned P1 table, with strict-majority fallback outside pilot size."""

    if enrolled_count < 1:
        raise ValueError("enrolled_count must be positive")
    return _STRICT_MAJORITY.get(enrolled_count, enrolled_count // 2 + 1)


def strict_majority_table() -> dict[int, int]:
    """Return a copy of the normative 6→4, 7→4, 8→5 table."""

    return dict(_STRICT_MAJORITY)


class MeasurementPlan(InventoriedModel):
    """One predeclared plan for one confirmed Success Contract.

    The object is editable until :meth:`lock` is called.  Once locked, every
    substantive assignment and ``model_copy(update=...)`` is rejected; the
    first collection timestamp must be at or after the hash-stamped lock.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    contract_id: str
    baseline_window: MeasurementWindow
    follow_up_window: MeasurementWindow
    meaningful_improvement_threshold: float = Field(alias="improvement_threshold")
    objective_signal: str
    objective_signal_required: bool = True
    missing_data_treatment: str = "not-success"
    dropout_treatment: str = "included-denominator-not-success"
    regression_definition: str
    near_miss_definition: str
    severe_failure_definition: str
    strict_majority_thresholds: dict[int, int] = Field(default_factory=strict_majority_table)
    created_at: datetime = Field(default_factory=utc_now)
    locked_at: datetime | None = None
    first_data_collection_at: datetime | None = None
    content_hash: str | None = None

    _LOCKED_FIELDS = frozenset(
        {
            "contract_id",
            "baseline_window",
            "follow_up_window",
            "meaningful_improvement_threshold",
            "objective_signal",
            "objective_signal_required",
            "missing_data_treatment",
            "dropout_treatment",
            "regression_definition",
            "near_miss_definition",
            "severe_failure_definition",
            "strict_majority_thresholds",
            "created_at",
            "locked_at",
            "first_data_collection_at",
            "content_hash",
        }
    )

    @field_validator("contract_id", "objective_signal")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=512)

    @field_validator(
        "missing_data_treatment",
        "dropout_treatment",
        "regression_definition",
        "near_miss_definition",
        "severe_failure_definition",
    )
    @classmethod
    def _definitions(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=1024)

    @field_validator("created_at", "locked_at", "first_data_collection_at")
    @classmethod
    def _aware(cls, value: datetime | None, info: Any) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value

    @field_validator("strict_majority_thresholds")
    @classmethod
    def _thresholds(cls, value: dict[int, int]) -> dict[int, int]:
        expected = strict_majority_table()
        if value != expected:
            raise ValueError(
                "strict_majority_thresholds are normative and must be exactly "
                "6→4, 7→4, 8→5"
            )
        return dict(value)

    @model_validator(mode="after")
    def _state(self) -> Self:
        if self.meaningful_improvement_threshold < 0:
            raise ValueError("improvement_threshold must be non-negative")
        if self.follow_up_window.start <= self.baseline_window.end:
            raise ValueError(
                "follow-up window must begin after the baseline window ends"
            )
        if self.locked_at is None:
            if self.content_hash is not None:
                raise ValueError("unlocked measurement plan cannot carry content_hash")
            if self.first_data_collection_at is not None:
                raise ValueError("first data collection requires a locked plan")
        else:
            expected = self.canonical_hash()
            if self.content_hash != expected:
                raise ValueError("locked plan content_hash does not match canonical plan")
            if (
                self.first_data_collection_at is not None
                and self.first_data_collection_at < self.locked_at
            ):
                raise ValueError("first data collection cannot predate plan lock")
        return self

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._LOCKED_FIELDS and getattr(self, "locked_at", None) is not None:
            raise MeasurementPlanError(
                f"measurement plan is hash-locked; field {name!r} cannot be edited"
            )
        super().__setattr__(name, value)

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={"created_at", "locked_at", "first_data_collection_at", "content_hash"},
        )

    def canonical_hash(self) -> str:
        return content_hash(self.canonical_payload())

    @property
    def plan_hash(self) -> str | None:
        return self.content_hash

    @property
    def hash(self) -> str | None:
        """Short alias used by manifest/consent stores."""

        return self.content_hash

    @property
    def first_collection_at(self) -> datetime | None:
        return self.first_data_collection_at

    @property
    def locked(self) -> bool:
        return self.locked_at is not None and self.content_hash is not None

    def lock(self, *, at: datetime | None = None) -> MeasurementPlan:
        """Stamp and lock the plan before any participant data is collected."""

        if self.locked:
            return self
        when = at or utc_now()
        if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
            raise MeasurementPlanError("lock timestamp must be timezone-aware")
        object.__setattr__(self, "locked_at", when)
        object.__setattr__(self, "content_hash", self.canonical_hash())
        return self

    def mark_first_collection(self, *, at: datetime | None = None) -> MeasurementPlan:
        """Record the first collection event; post-lock edits remain refused."""

        if not self.locked:
            raise MeasurementPlanError("a measurement plan must be locked before first data")
        when = at or utc_now()
        if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
            raise MeasurementPlanError("first collection timestamp must be timezone-aware")
        if when < self.locked_at:  # type: ignore[operator]
            raise MeasurementPlanError("first collection cannot predate plan lock")
        if self.first_data_collection_at is not None:
            if self.first_data_collection_at == when:
                return self
            raise MeasurementPlanError("first collection timestamp is already recorded")
        object.__setattr__(self, "first_data_collection_at", when)
        return self

    def assert_admissible(self, *, first_collection_at: datetime | None = None) -> None:
        """Refuse analysis unless hash and temporal process controls hold."""

        if not self.locked or self.content_hash != self.canonical_hash():
            raise MeasurementPlanError("no valid hash-locked measurement plan exists")
        collection = self.first_data_collection_at
        if collection is None:
            raise MeasurementPlanError("first data collection timestamp is missing")
        if first_collection_at is not None and first_collection_at != collection:
            raise MeasurementPlanError(
                "supplied first collection timestamp does not match the recorded event"
            )
        if collection < self.locked_at:  # type: ignore[operator]
            raise MeasurementPlanError("measurement plan was locked after first data collection")

    def threshold_for(self, enrolled_count: int) -> int:
        if enrolled_count in self.strict_majority_thresholds:
            return self.strict_majority_thresholds[enrolled_count]
        return strict_majority_threshold(enrolled_count)

    def model_copy(self, *, update: dict[str, object] | None = None, deep: bool = False) -> Self:
        updates = update or {}
        if self.locked and any(name in self._LOCKED_FIELDS for name in updates):
            raise MeasurementPlanError("hash-locked measurement plan cannot be edited")
        copied = super().model_copy(update=update, deep=deep)
        if copied.locked:
            object.__setattr__(copied, "content_hash", copied.canonical_hash())
        return copied


# Explicit alias used by callers that want the post-lock type in annotations.
LockedMeasurementPlan = MeasurementPlan
MeasurementPlanTemplate = MeasurementPlan


def canonical_plan_hash(plan: MeasurementPlan) -> str:
    """Hash helper for process-control stores and release manifests."""

    return plan.canonical_hash()
