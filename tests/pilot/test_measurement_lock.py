from datetime import UTC, datetime, timedelta

import pytest

from capability_exchange.pilot.measurement import (
    MeasurementPlan,
    MeasurementPlanError,
    strict_majority_threshold,
)


def plan(now: datetime) -> MeasurementPlan:
    return MeasurementPlan(
        contract_id="weekly-review",
        baseline_window={"start": now, "end": now + timedelta(days=1)},
        follow_up_window={"start": now + timedelta(days=2), "end": now + timedelta(days=3)},
        improvement_threshold=1,
        objective_signal="receipt count",
        regression_definition="below baseline",
        near_miss_definition="improved below threshold",
        severe_failure_definition="trust-floor failure",
    )


def test_strict_majority_table_is_pinned() -> None:
    assert {n: strict_majority_threshold(n) for n in (6, 7, 8)} == {6: 4, 7: 4, 8: 5}


def test_lock_hashes_and_refuses_edits_after_first_data() -> None:
    now = datetime.now(UTC)
    measured = plan(now).lock(at=now)
    measured.mark_first_collection(at=now + timedelta(minutes=1))
    with pytest.raises(MeasurementPlanError):
        measured.objective_signal = "changed"  # type: ignore[misc]
    with pytest.raises(MeasurementPlanError):
        measured.model_copy(update={"near_miss_definition": "post hoc"})
    measured.assert_admissible()


def test_lock_after_collection_is_rejected() -> None:
    now = datetime.now(UTC)
    measured = plan(now).lock(at=now + timedelta(days=2))
    with pytest.raises(MeasurementPlanError):
        measured.assert_admissible(first_collection_at=now)


def test_baseline_and_follow_up_windows_cannot_overlap_or_reverse() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="follow-up window must begin after"):
        MeasurementPlan(
            contract_id="weekly-review",
            baseline_window={"start": now, "end": now + timedelta(days=2)},
            follow_up_window={"start": now + timedelta(days=1), "end": now + timedelta(days=3)},
            improvement_threshold=1,
            objective_signal="receipt count",
            regression_definition="below baseline",
            near_miss_definition="improved below threshold",
            severe_failure_definition="trust-floor failure",
        )


def test_first_collection_timestamp_is_write_once_and_cannot_be_overridden() -> None:
    now = datetime.now(UTC)
    measured = plan(now).lock(at=now)
    first = now + timedelta(minutes=1)
    measured.mark_first_collection(at=first)
    with pytest.raises(MeasurementPlanError, match="already recorded"):
        measured.mark_first_collection(at=first + timedelta(days=1))
    with pytest.raises(MeasurementPlanError, match="does not match"):
        measured.assert_admissible(first_collection_at=first + timedelta(days=1))
