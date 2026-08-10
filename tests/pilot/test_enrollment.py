from datetime import UTC, datetime

import pytest

from capability_exchange.jobs.contract import JobBoundaries, SuccessContract
from capability_exchange.pilot.enrollment import (
    EnrollmentError,
    EnrollmentGate,
    ParticipantDeletionEvidence,
    ParticipantDeletionManifest,
)
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


def test_enrollment_has_no_red_team_bypass_switch() -> None:
    current = protocol(red_team_complete=False)
    with pytest.raises(TypeError):
        EnrollmentGate(current, require_red_team=False)  # type: ignore[call-arg]


class DeletionPort:
    def __init__(self, verified: bool) -> None:
        self.verified = verified
        self.calls = 0

    def delete_participant(self, record) -> ParticipantDeletionManifest:
        self.calls += 1
        return ParticipantDeletionManifest(
            participant_id=record.participant_id,
            protocol_version=record.protocol_version,
            protocol_hash=record.protocol_hash,
            withdrawal_requested_at=record.consent.withdrawal_requested_at,
            stores=tuple(
                ParticipantDeletionEvidence(
                    store_id=store_id,
                    artifact_hashes=("sha256:" + str(index) * 64,),
                    deleted=self.verified,
                    verified_at=record.consent.withdrawal_requested_at,
                    verifier_id="synthetic-deletion-executor",
                )
                for index, store_id in enumerate(
                    ("receipts", "caches", "browser-state"), start=1
                )
            ),
        )


def test_withdrawal_requires_verified_controlled_store_deletion() -> None:
    current = protocol()
    gate = EnrollmentGate(current)
    enrolled = gate.enroll(consent(current.protocol_hash), contract())
    failing = DeletionPort(False)
    with pytest.raises(EnrollmentError, match="deletion could not be verified"):
        gate.withdraw(enrolled.participant_id, deletion_port=failing)
    assert gate.records == ()
    assert gate.tombstones[0].consent.status == "withdrawn"
    assert gate.tombstones[0].consent.deletion_confirmed_at is None

    with pytest.raises(EnrollmentError, match="permanently withdrawn"):
        gate.enroll(consent(current.protocol_hash), contract())


def test_successful_withdrawal_keeps_a_permanent_protocol_tombstone() -> None:
    current = protocol()
    gate = EnrollmentGate(current)
    enrolled = gate.enroll(consent(current.protocol_hash), contract())

    verified = DeletionPort(True)
    withdrawn = gate.withdraw(enrolled.participant_id, deletion_port=verified)
    assert withdrawn.consent.status == "withdrawn"
    assert withdrawn.consent.deletion_confirmed_at is not None
    assert gate.records == ()
    assert gate.tombstones == (withdrawn,)
    with pytest.raises(EnrollmentError, match="permanently withdrawn"):
        gate.enroll(consent(current.protocol_hash), contract())


def test_deletion_manifest_cannot_omit_a_controlled_participant_store() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="receipts, caches, and browser-state"):
        ParticipantDeletionManifest(
            participant_id="p1",
            protocol_version="v1",
            protocol_hash="a" * 64,
            withdrawal_requested_at=now,
            stores=(
                ParticipantDeletionEvidence(
                    store_id="receipts",
                    artifact_hashes=("sha256:" + "a" * 64,),
                    deleted=True,
                    verified_at=now,
                    verifier_id="deletion-executor",
                ),
            ),
        )
