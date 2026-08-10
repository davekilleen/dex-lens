from datetime import UTC, datetime, timedelta

from capability_exchange.pilot.analysis import ParticipantMeasurement, PilotVerdict, analyze_pilot
from capability_exchange.pilot.learning import normalize_learning
from capability_exchange.pilot.measurement import MeasurementPlan


def make_plan(now: datetime) -> MeasurementPlan:
    return MeasurementPlan(
        contract_id="job",
        baseline_window={"start": now, "end": now + timedelta(days=1)},
        follow_up_window={"start": now + timedelta(days=2), "end": now + timedelta(days=3)},
        improvement_threshold=1,
        objective_signal="objective receipt",
        regression_definition="regression",
        near_miss_definition="near miss",
        severe_failure_definition="severe trust failure",
    ).lock(at=now)


def row(
    i: int,
    now: datetime,
    *,
    improved: bool = True,
    **kwargs: object,
) -> ParticipantMeasurement:
    values: dict[str, object] = {
        "participant_id": f"p{i}",
        "contract_id": "job",
        "baseline_value": 0,
        "follow_up_value": 2 if improved else 0,
        "baseline_state": "observed",
        "follow_up_state": "observed",
        "baseline_objective_signal": True,
        "follow_up_objective_signal": True,
        "baseline_captured_at": now,
        "follow_up_captured_at": now + timedelta(days=2),
    }
    values.update(kwargs)
    return ParticipantMeasurement(
        **values,
    )


def test_three_of_seven_is_not_demonstrated_and_cards_do_not_rescue() -> None:
    now = datetime.now(UTC)
    records = [row(i, now, improved=i < 3, card_contribution_count=99) for i in range(7)]
    report = analyze_pilot(records, make_plan(now))
    assert report.verdict is PilotVerdict.NOT_DEMONSTRATED
    assert report.improved_count == 3
    assert report.card_learning_count == 693


def test_four_of_seven_clean_is_successful_but_severe_failure_stops() -> None:
    now = datetime.now(UTC)
    clean = analyze_pilot([row(i, now, improved=i < 4) for i in range(7)], make_plan(now))
    assert clean.verdict is PilotVerdict.SUCCESSFUL
    stopped = analyze_pilot(
        [
            row(
                i,
                now,
                improved=i < 4,
                severe_failure=i == 0,
                severe_failure_type="Recovery failed",
            )
            for i in range(7)
        ],
        make_plan(now),
    )
    assert stopped.verdict is PilotVerdict.STOP_AND_REVIEW
    assert stopped.trust_floor_stop


def test_missing_follow_up_and_self_report_only_are_not_imputed() -> None:
    now = datetime.now(UTC)
    records = [row(i, now, improved=True) for i in range(7)]
    records[0] = row(0, now, improved=True, missing_follow_up=True)
    records[1] = row(
        1,
        now,
        improved=True,
        self_report_only=True,
        baseline_objective_signal=False,
        follow_up_objective_signal=False,
    )
    report = analyze_pilot(records, make_plan(now))
    assert report.improved_count == 5
    assert report.verdict is PilotVerdict.SUCCESSFUL
    assert any(result.evidence_limited for result in report.participant_results[:2])


def test_normalized_learning_excludes_planted_canary() -> None:
    now = datetime.now(UTC)
    report = analyze_pilot([row(i, now, improved=i < 3) for i in range(7)], make_plan(now))
    output = normalize_learning(report, private_values=("PRIVATE-CANARY-123",))
    assert "PRIVATE-CANARY-123" not in output.model_dump_json()
    assert output.raw_private_evidence_included is False
