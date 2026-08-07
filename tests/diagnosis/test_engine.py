"""Diagnosis engine behavior (M-D): deterministic, honest, fail closed."""

from __future__ import annotations

from datetime import timedelta

import pytest
from tests.diagnosis.conftest import (
    COLLECTED_AT,
    contract,
    envelope,
    item,
    observed_probe,
    presence_only_envelope,
    probe,
)

from capability_exchange.adapter import InstrumentHealth
from capability_exchange.diagnosis import (
    CapabilityState,
    DiagnosisInputError,
    Finding,
    FoundationCapability,
    SafetyBoundary,
    assess,
)
from capability_exchange.evidence import (
    EvidenceItem,
    EvidenceLevel,
    EvidenceState,
    evidence_level,
)
from capability_exchange.jobs import InspectionJob, SuccessContract


def find(map_, capability: FoundationCapability, job_id: str = "weekly-report") -> Finding:
    (job,) = [job for job in map_.jobs if job.job_id == job_id]
    (found,) = [f for f in job.findings if f.capability is capability]
    return found


class TestJobsFirstShape:
    def test_one_entry_per_confirmed_job_with_all_eight_capabilities(self) -> None:
        map_ = assess([contract("alpha-job"), contract("beta-job")], presence_only_envelope())
        assert [job.job_id for job in map_.jobs] == ["alpha-job", "beta-job"]
        for job in map_.jobs:
            assert {f.capability for f in job.findings} == set(FoundationCapability)

    def test_every_finding_carries_implication_and_one_next_move(self) -> None:
        map_ = assess([contract()], presence_only_envelope())
        for finding in map_.jobs[0].findings:
            assert finding.practical_implication.strip()
            assert finding.recommended_next_move.strip()

    def test_assessed_at_defaults_to_collection_time(self) -> None:
        map_ = assess([contract()], presence_only_envelope())
        assert map_.assessed_at == COLLECTED_AT


class TestDeterminism:
    def test_same_inputs_yield_identical_maps(self) -> None:
        first = assess([contract()], presence_only_envelope())
        second = assess([contract()], presence_only_envelope())
        assert first == second
        assert first.model_dump() == second.model_dump()

    def test_contract_order_does_not_matter(self) -> None:
        env = presence_only_envelope()
        forward = assess([contract("alpha-job"), contract("beta-job")], env)
        backward = assess([contract("beta-job"), contract("alpha-job")], env)
        assert forward == backward


class TestOnlyConfirmedContractsAreConsumable:
    def test_an_inspection_job_is_rejected(self) -> None:
        draft = InspectionJob(
            job_id="draft-job",
            title="A draft the person never confirmed",
            situation="Some situation",
            desired_outcome="Some outcome",
            created_at=COLLECTED_AT,
        )
        with pytest.raises(DiagnosisInputError, match="Inspection"):
            assess([draft], presence_only_envelope())

    def test_a_mix_containing_an_inspection_job_is_rejected_whole(self) -> None:
        draft = InspectionJob(
            job_id="draft-job",
            title="A draft the person never confirmed",
            situation="Some situation",
            desired_outcome="Some outcome",
            created_at=COLLECTED_AT,
        )
        with pytest.raises(DiagnosisInputError):
            assess([contract(), draft], presence_only_envelope())

    def test_a_contract_lookalike_mapping_is_rejected(self) -> None:
        lookalike = contract().model_dump()
        with pytest.raises(DiagnosisInputError):
            assess([lookalike], presence_only_envelope())

    def test_no_confirmed_contracts_means_no_diagnosis(self) -> None:
        with pytest.raises(DiagnosisInputError, match="nothing to assess"):
            assess([], presence_only_envelope())

    def test_duplicate_job_ids_are_rejected(self) -> None:
        with pytest.raises(DiagnosisInputError, match="duplicate"):
            assess([contract(), contract()], presence_only_envelope())

    def test_a_non_envelope_scope_is_rejected(self) -> None:
        with pytest.raises(DiagnosisInputError, match="approved scope"):
            assess([contract()], {"probes": []})  # type: ignore[arg-type]


class TestPresenceIsNeverOutcome:
    def test_presence_only_envelope_yields_no_working_and_no_verified(self) -> None:
        """The M1 adapter's real probes are all configuration presence:
        no finding may be Working, none may be Verified."""
        map_ = assess([contract()], presence_only_envelope())
        for finding in map_.jobs[0].findings:
            assert finding.capability_state is not CapabilityState.WORKING
            assert finding.evidence_level is not EvidenceLevel.VERIFIED

    def test_presence_lands_as_not_demonstrated_where_relevant(self) -> None:
        map_ = assess([contract()], presence_only_envelope())
        health = find(map_, FoundationCapability.HONEST_HEALTH_OBSERVABILITY)
        assert health.capability_state is CapabilityState.NOT_DEMONSTRATED
        assert any("presence alone" in note for note in health.uncertainty_notes)

    def test_presence_evidence_is_restated_insufficient(self) -> None:
        map_ = assess([contract()], presence_only_envelope())
        health = find(map_, FoundationCapability.HONEST_HEALTH_OBSERVABILITY)
        assert health.evidence
        assert all(
            evidence.state is EvidenceState.INSUFFICIENT for evidence in health.evidence
        )

    def test_an_observed_recent_real_example_grounds_working_verified(self) -> None:
        map_ = assess(
            [contract()],
            envelope(observed_probe("rollback-demonstrated", "receipt:rollback-1")),
        )
        recovery = find(map_, FoundationCapability.SAFE_CHANGE_RECOVERY)
        assert recovery.capability_state is CapabilityState.WORKING
        assert recovery.evidence_level is EvidenceLevel.VERIFIED

    def test_outcome_plus_presence_stays_working_verified(self) -> None:
        """Presence evidence corroborates a directly observed outcome; it
        only degrades when it stands alone."""
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("skills-present"),
                observed_probe("live-check", "receipt:live-check-1"),
            ),
        )
        health = find(map_, FoundationCapability.HONEST_HEALTH_OBSERVABILITY)
        assert health.capability_state is CapabilityState.WORKING
        assert health.evidence_level is EvidenceLevel.VERIFIED

    def test_user_report_plus_presence_never_verifies(self) -> None:
        """A person's account plus file presence caps at Reported: presence
        cannot lift an unobserved outcome to Verified."""
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("skills-present"),
                probe(
                    "live-check",
                    item(EvidenceState.USER_REPORTED, "note:person-account"),
                ),
            ),
        )
        health = find(map_, FoundationCapability.HONEST_HEALTH_OBSERVABILITY)
        assert health.evidence_level is EvidenceLevel.REPORTED
        assert health.capability_state is CapabilityState.PARTIAL


class TestRecentRealExamples:
    def test_stale_outcome_evidence_does_not_ground_working(self) -> None:
        """Diagnosis assesses recent real examples: an outcome observed long
        ago degrades to stale and supports nothing."""
        old = EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=COLLECTED_AT - timedelta(days=120),
            stale_after=timedelta(days=30),
            reference="receipt:rollback-old",
        )
        map_ = assess(
            [contract()],
            envelope(probe("rollback-demonstrated", old)),
            assessed_at=COLLECTED_AT,
        )
        recovery = find(map_, FoundationCapability.SAFE_CHANGE_RECOVERY)
        assert recovery.capability_state is CapabilityState.NOT_DEMONSTRATED
        assert recovery.evidence_level is not EvidenceLevel.VERIFIED
        assert any("stale" in note for note in recovery.uncertainty_notes)


class TestInstrumentFailureStaysVisible:
    def test_failed_instruments_yield_unknown_not_working(self) -> None:
        map_ = assess(
            [contract()],
            envelope(
                probe(
                    "rollback-demonstrated",
                    health=InstrumentHealth.COULD_NOT_CHECK,
                    detail="scope did not include the backup area",
                )
            ),
        )
        recovery = find(map_, FoundationCapability.SAFE_CHANGE_RECOVERY)
        assert recovery.capability_state is CapabilityState.UNKNOWN
        assert recovery.evidence_level is EvidenceLevel.UNKNOWN
        assert any("could not assess" in note for note in recovery.uncertainty_notes)

    def test_a_failure_beside_an_outcome_caps_at_partial(self) -> None:
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("rollback-demonstrated", "receipt:rollback-1"),
                probe(
                    "recovery-demonstrated",
                    health=InstrumentHealth.BROKEN,
                    detail="the recovery probe crashed",
                ),
            ),
        )
        recovery = find(map_, FoundationCapability.SAFE_CHANGE_RECOVERY)
        assert recovery.capability_state is CapabilityState.PARTIAL
        assert any("could not assess" in note for note in recovery.uncertainty_notes)

    def test_intentionally_off_reads_as_honest_absence(self) -> None:
        map_ = assess(
            [contract()],
            envelope(
                probe(
                    "rollback-demonstrated",
                    health=InstrumentHealth.INTENTIONALLY_OFF,
                    detail="the person disabled rollback rehearsals",
                )
            ),
        )
        recovery = find(map_, FoundationCapability.SAFE_CHANGE_RECOVERY)
        assert recovery.capability_state is CapabilityState.NOT_DEMONSTRATED
        assert recovery.capability_state is not CapabilityState.WORKING


class TestSafetyBoundaryAxis:
    def test_working_verified_and_still_overbroad(self) -> None:
        """#351 amendment, engine-level: an approval-receipted outcome with
        observed write access beyond the job is Working, Verified, Overbroad."""
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("approval-receipt", "receipt:approval-1"),
                observed_probe("write-access-observed", "config:broad-permissions"),
            ),
        )
        agency = find(map_, FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL)
        assert agency.capability_state is CapabilityState.WORKING
        assert agency.evidence_level is EvidenceLevel.VERIFIED
        assert agency.safety_boundary is SafetyBoundary.OVERBROAD

    def test_safe_requires_boundary_evidence_plus_this_jobs_outcome(self) -> None:
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("approval-receipt", "receipt:approval-1"),
                observed_probe("permission-boundary-observed", "config:permission-set"),
            ),
        )
        agency = find(map_, FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL)
        assert agency.safety_boundary is SafetyBoundary.SAFE

    def test_boundary_evidence_alone_is_never_safe(self) -> None:
        """Safe is scoped to the assessed job: without a demonstrated outcome
        for this job there is nothing the boundary is safe FOR."""
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("permission-boundary-observed", "config:permission-set")
            ),
        )
        agency = find(map_, FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL)
        assert agency.safety_boundary is SafetyBoundary.UNCLEAR

    def test_no_boundary_evidence_stays_unclear_never_assumed_safe(self) -> None:
        map_ = assess(
            [contract()],
            envelope(observed_probe("approval-receipt", "receipt:approval-1")),
        )
        agency = find(map_, FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL)
        assert agency.safety_boundary is SafetyBoundary.UNCLEAR
        assert any("unclear" in note for note in agency.uncertainty_notes)

    def test_safe_never_blankets_across_capabilities(self) -> None:
        """One capability's demonstrated safety says nothing about another's."""
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("approval-receipt", "receipt:approval-1"),
                observed_probe("permission-boundary-observed", "config:permission-set"),
            ),
        )
        for finding in map_.jobs[0].findings:
            if finding.capability is not FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL:
                assert finding.safety_boundary is not SafetyBoundary.SAFE


class TestR2Integration:
    def test_every_level_derives_through_the_total_mapping(self) -> None:
        """R2 integration: display state branches only on the closed
        vocabulary, and each finding's level equals the mapping's answer."""
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("rollback-demonstrated", "receipt:rollback-1"),
                observed_probe("skills-present"),
                probe(
                    "live-check",
                    health=InstrumentHealth.BROKEN,
                    detail="live check crashed",
                ),
            ),
        )
        for finding in map_.jobs[0].findings:
            assert finding.evidence_level is evidence_level(
                evidence.state for evidence in finding.evidence
            )

    def test_every_linked_state_is_in_the_closed_vocabulary(self) -> None:
        map_ = assess([contract()], presence_only_envelope())
        for finding in map_.jobs[0].findings:
            for evidence in finding.evidence:
                assert isinstance(evidence.state, EvidenceState)

    def test_unmatched_probes_ground_no_finding(self) -> None:
        """Evidence outside the declared observable-evidence patterns —
        e.g. unrelated or secret-bearing material — contributes nothing."""
        map_ = assess(
            [contract()],
            envelope(observed_probe("planted-secret-content", "path:unrelated")),
        )
        for finding in map_.jobs[0].findings:
            assert finding.evidence == ()
            assert finding.capability_state is CapabilityState.UNKNOWN


class TestReadOnlyDiagnosis:
    def test_assess_writes_nothing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assess([contract()], presence_only_envelope())
        assert list(tmp_path.iterdir()) == []

    def test_diagnosis_package_exposes_no_mutating_entry_point(self) -> None:
        import capability_exchange.diagnosis as package

        mutating_tokens = ("write", "apply", "heal", "adopt", "adapt", "mutate", "repair")
        for symbol in package.__all__:
            lowered = symbol.lower()
            for token in mutating_tokens:
                assert token not in lowered


def test_finding_evidence_serializes_only_non_raw_references(
    confirmed_contract: SuccessContract,
) -> None:
    """G2: every linked evidence reference in a finding is a locator/digest,
    never raw content — enforced by the EvidenceItem schema the finding links."""
    map_ = assess([confirmed_contract], presence_only_envelope())
    payload = map_.model_dump()
    for job in payload["jobs"]:
        for finding in job["findings"]:
            for evidence in finding["evidence"]:
                assert len(evidence["reference"]) <= 512
                assert "\n" not in evidence["reference"]
