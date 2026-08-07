"""#351/#352 conformance (M2 acceptance criteria, HANDOFF Section 4, verbatim):

    "every finding carries exactly the three independent axes; no aggregate
    score, maturity rank, or resemblance percentage is representable in any
    schema or report template (schema test, not code review); diagnosis
    consumes only confirmed Success Contracts + approved scope;
    presence-of-configuration alone never yields Working or Verified
    (fixture test)."

    "R2 integration: diagnosis display and eligibility branch only on the
    closed state vocabulary."

Each criterion below is tested against gates.md / HANDOFF wording, with the
presence rule additionally property-tested over arbitrary configuration-only
envelopes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.diagnosis.conftest import (
    COLLECTED_AT,
    contract,
    envelope,
    observed_probe,
    presence_only_envelope,
)

from capability_exchange.capmap import CapabilityMap, JobFindings
from capability_exchange.diagnosis import (
    CapabilityState,
    DiagnosisInputError,
    Finding,
    FoundationCapability,
    SafetyBoundary,
    assess,
    definition_for,
)
from capability_exchange.diagnosis.finding import CapabilityState as StateEnum
from capability_exchange.evidence import EvidenceLevel, EvidenceState, evidence_level
from capability_exchange.jobs import InspectionJob


class TestExactlyThreeIndependentAxes:
    """Criterion: every finding carries exactly the three independent axes."""

    AXIS_FIELDS = {
        "capability_state": StateEnum,
        "evidence_level": EvidenceLevel,
        "safety_boundary": SafetyBoundary,
    }

    def test_the_finding_schema_has_exactly_the_three_axis_fields(self) -> None:
        axis_typed = {
            name: info.annotation
            for name, info in Finding.model_fields.items()
            if info.annotation in (StateEnum, EvidenceLevel, SafetyBoundary)
        }
        assert axis_typed == self.AXIS_FIELDS

    def test_axis_vocabularies_are_the_351_amendment_verbatim(self) -> None:
        assert {s.value for s in CapabilityState} == {
            "working",
            "partial",
            "not-demonstrated",
            "unknown",
        }
        assert {level.value for level in EvidenceLevel} == {
            "verified",
            "supported",
            "reported",
            "unknown",
        }
        assert {b.value for b in SafetyBoundary} == {"safe", "overbroad", "unclear"}

    def test_every_produced_finding_carries_all_three_axes(self) -> None:
        map_ = assess([contract()], presence_only_envelope())
        for finding in map_.jobs[0].findings:
            assert isinstance(finding.capability_state, CapabilityState)
            assert isinstance(finding.evidence_level, EvidenceLevel)
            assert isinstance(finding.safety_boundary, SafetyBoundary)

    def test_working_and_verified_can_still_be_overbroad(self) -> None:
        """The axes are independent: engine-produced proof (also covered as
        an engine fixture)."""
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("approval-receipt", "receipt:approval-1"),
                observed_probe("write-access-observed", "config:broad-permissions"),
            ),
        )
        (job,) = map_.jobs
        (agency,) = [
            f
            for f in job.findings
            if f.capability is FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL
        ]
        assert agency.capability_state is CapabilityState.WORKING
        assert agency.evidence_level is EvidenceLevel.VERIFIED
        assert agency.safety_boundary is SafetyBoundary.OVERBROAD


class TestOnlyConfirmedContractsAndApprovedScope:
    """Criterion: diagnosis consumes only confirmed Success Contracts +
    approved scope."""

    def test_assess_takes_exactly_two_data_inputs(self) -> None:
        import inspect

        from capability_exchange.diagnosis import engine

        parameters = inspect.signature(engine.assess).parameters
        assert list(parameters) == ["confirmed_contracts", "envelope", "assessed_at"]

    def test_an_inspection_state_job_is_rejected(self) -> None:
        draft = InspectionJob(
            job_id="draft-job",
            title="Never confirmed",
            situation="Some situation",
            desired_outcome="Some outcome",
            created_at=COLLECTED_AT,
        )
        with pytest.raises(DiagnosisInputError):
            assess([draft], presence_only_envelope())

    def test_nothing_but_a_success_contract_enters(self) -> None:
        for impostor in (
            contract().model_dump(),
            "weekly-report",
            None,
            object(),
        ):
            with pytest.raises(DiagnosisInputError):
                assess([impostor], presence_only_envelope())


#: The configuration/presence probe-id vocabulary across all eight
#: capabilities — the corpus for the presence property test.
ALL_CONFIGURATION_PATTERNS = sorted(
    {
        pattern
        for capability in FoundationCapability
        for pattern in definition_for(capability).configuration_probe_patterns
    }
)


class TestPresenceAloneNeverWorkingOrVerified:
    """Criterion (fixture test): presence of a skill, tool, integration, or
    configuration alone never yields Working or Verified."""

    def test_the_m1_adapter_presence_probes(self) -> None:
        map_ = assess([contract()], presence_only_envelope())
        for finding in map_.jobs[0].findings:
            assert finding.capability_state is not CapabilityState.WORKING
            assert finding.evidence_level is not EvidenceLevel.VERIFIED

    @given(
        chosen=st.lists(
            st.sampled_from(ALL_CONFIGURATION_PATTERNS), min_size=1, max_size=8, unique=True
        )
    )
    def test_any_configuration_only_envelope_never_yields_working_or_verified(
        self, chosen: list[str]
    ) -> None:
        env = envelope(
            *(observed_probe(pattern, f"path:{pattern}") for pattern in sorted(chosen))
        )
        map_ = assess([contract()], env)
        for finding in map_.jobs[0].findings:
            assert finding.capability_state is not CapabilityState.WORKING, (
                f"{finding.capability.value} reached Working from configuration "
                f"presence alone ({chosen})"
            )
            assert finding.evidence_level is not EvidenceLevel.VERIFIED, (
                f"{finding.capability.value} reached Verified from configuration "
                f"presence alone ({chosen})"
            )


class TestR2Integration:
    """Criterion: diagnosis display and eligibility branch only on the
    closed state vocabulary."""

    def test_every_linked_evidence_state_is_a_closed_vocabulary_member(self) -> None:
        map_ = assess([contract()], presence_only_envelope())
        for finding in map_.jobs[0].findings:
            for evidence in finding.evidence:
                assert isinstance(evidence.state, EvidenceState)

    def test_every_evidence_level_derives_through_the_total_mapping(self) -> None:
        map_ = assess(
            [contract()],
            envelope(
                observed_probe("rollback-demonstrated", "receipt:rollback-1"),
                observed_probe("skills-present"),
            ),
        )
        for finding in map_.jobs[0].findings:
            assert finding.evidence_level is evidence_level(
                evidence.state for evidence in finding.evidence
            )

    def test_a_finding_asserting_a_level_off_the_mapping_is_unrepresentable(
        self,
    ) -> None:
        from pydantic import ValidationError
        from tests.diagnosis.conftest import item

        with pytest.raises(ValidationError):
            Finding(
                capability=FoundationCapability.SAFE_CHANGE_RECOVERY,
                job_id="weekly-report",
                capability_state=CapabilityState.NOT_DEMONSTRATED,
                evidence_level=EvidenceLevel.VERIFIED,
                safety_boundary=SafetyBoundary.UNCLEAR,
                evidence=(item(EvidenceState.INSUFFICIENT, "path:.claude/skills"),),
                practical_implication="Recovery protects what already works",
                why_it_matters="Trustworthy recovery keeps this job safe to improve",
                recommended_next_move="Rehearse a rollback once",
            )


class TestJobsFirstReportShape:
    """#352: findings nest inside the person's confirmed jobs, with the
    Evidence Level shown for every finding."""

    def test_the_map_is_organized_by_confirmed_job(self) -> None:
        map_ = assess(
            [contract("alpha-job"), contract("beta-job")], presence_only_envelope()
        )
        assert isinstance(map_, CapabilityMap)
        assert [job.job_id for job in map_.jobs] == ["alpha-job", "beta-job"]
        for job in map_.jobs:
            assert isinstance(job, JobFindings)
            for finding in job.findings:
                assert finding.job_id == job.job_id
                assert isinstance(finding.evidence_level, EvidenceLevel)

    def test_assessment_time_is_honest_and_timezone_aware(self) -> None:
        later = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
        map_ = assess([contract()], presence_only_envelope(), assessed_at=later)
        assert map_.assessed_at == later
