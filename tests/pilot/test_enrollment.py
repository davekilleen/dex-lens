from datetime import UTC, datetime

import pytest

from capability_exchange.jobs.contract import JobBoundaries, SuccessContract
from capability_exchange.pilot.enrollment import EnrollmentError, EnrollmentGate
from capability_exchange.pilot.protocol import ConsentRecord

from .test_protocol import protocol


def contract() -> SuccessContract:
    return SuccessContract(
        job_id="weekly-review",
        situation="weekly review",
        desired_outcome="complete review",
        success_evidence=("review receipt",),
        boundaries=JobBoundaries(privacy_limits=(), approval_limits=(), autonomy_limits=()),
        importance="high",
        cadence="weekly",
        confirmed_at=datetime.now(UTC),
    )


def consent(protocol_hash: str) -> ConsentRecord:
    return ConsentRecord(
        participant_id="p1",
        protocol_version="m6-v1",
        protocol_hash=protocol_hash,
        stratum_id="non-dex",
        evidence_scope=("weekly-review",),
        consented_at=datetime.now(UTC),
    )


def test_enrollment_requires_exact_protocol_hash() -> None:
    current = protocol()
    with pytest.raises(EnrollmentError, match="exact current protocol hash"):
        EnrollmentGate(current).enroll(consent("wrong"), contract())


def test_enrollment_requires_consent_and_confirmed_contract() -> None:
    current = protocol()
    gate = EnrollmentGate(current)
    with pytest.raises(EnrollmentError, match="recorded consent"):
        gate.enroll(None, contract())
    with pytest.raises(EnrollmentError, match="confirmed Success Contract"):
        gate.enroll(consent(current.protocol_hash), None)


def test_enrollment_accepts_matching_consent_contract() -> None:
    current = protocol()
    result = EnrollmentGate(current).enroll(consent(current.protocol_hash), contract())
    assert result.contract_id == "weekly-review"
