from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from capability_exchange.pilot.gate import FormalGateEvidence, GateRun, execute_pilot_gate
from capability_exchange.pilot.protocol import (
    ConsentRecord,
    PilotProtocol,
    ProtocolClause,
    ProtocolStratum,
)


def gate_report():
    commit = "a" * 40
    formal = tuple(
        FormalGateEvidence(
            evidence_id=evidence_id,
            commit=commit,
            producer="test executor",
            status="proven",
            artifact_sha256="b" * 64,
            test_ids=("tests/pilot/test_protocol.py",),
        )
        for evidence_id in (
            "formal:g1-bind-mount",
            "formal:m3-egress",
            "formal:m4-egress",
            "formal:m5-egress",
        )
    )
    with patch(
        "capability_exchange.pilot.gate._verified_repository_commit", return_value=commit
    ):
        return execute_pilot_gate(
            commit=commit,
            observed_at=datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
            runner=lambda test_ids: GateRun(exit_code=0, output="passed:" + test_ids[0]),
            formal_evidence=formal,
        )


def protocol(*, red_team_complete: bool = True) -> PilotProtocol:
    clause = ProtocolClause(
        owner="pilot owner",
        trigger="before touch",
        actions=("record",),
        evidence=("consent",),
        exit_criteria=("recorded",),
    )
    value = PilotProtocol(
        version="m6-v1",
        strata=(
            ProtocolStratum(
                id="non-dex", label="Non-Dex", minimum=4, maximum=5, description="non-Dex"
            ),
            ProtocolStratum(
                id="dex-customized",
                label="Dex/customized",
                minimum=2,
                maximum=3,
                description="customized",
            ),
        ),
        exclusions=("no contract",),
        evidence_consent=clause,
        withdrawal=clause,
        deletion=clause,
        adverse_event_reporting=clause,
        incident_response=clause,
    )
    return value.attach_red_team(gate_report()) if red_team_complete else value


def test_protocol_hash_is_canonical_and_changes_on_substantive_edit() -> None:
    first = protocol()
    second = protocol()
    assert first.protocol_hash == second.protocol_hash
    changed = first.model_copy(update={"exclusions": ("changed",)})
    assert changed.protocol_hash != first.protocol_hash


def test_consent_is_immutable_and_withdrawal_is_explicit() -> None:
    now = datetime.now(UTC)
    record = ConsentRecord(
        participant_id="p1",
        protocol_version="m6-v1",
        protocol_hash=protocol().protocol_hash,
        stratum_id="non-dex",
        evidence_scope=("job-outcome",),
        consented_at=now,
    )
    with pytest.raises((TypeError, ValueError)):
        record.status = "withdrawn"  # type: ignore[misc]
    withdrawn = record.withdraw(at=now)
    assert withdrawn.status == "withdrawn"
    assert record.status == "active"


def test_protocol_requires_unique_valid_strata() -> None:
    base = protocol()
    with pytest.raises(ValueError, match="strata ids"):
        base.model_copy(
            update={
                "strata": (
                    base.strata[0],
                    base.strata[0],
                )
            }
        )


def test_protocol_binds_the_exact_executed_gate_report() -> None:
    current = protocol()
    assert current.pilot_gate_report is not None
    assert current.pilot_gate_report.commit == "a" * 40
    assert current.pilot_gate_report.content_hash
    current.assert_red_team_ready()


def test_protocol_without_executed_gate_report_cannot_touch_participants() -> None:
    with pytest.raises(ValueError, match="exact-build gate"):
        protocol(red_team_complete=False).assert_red_team_ready()
