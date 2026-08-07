"""Nesting structure of the jobs-first Capability Map (M-D; #352, R1).

Findings nest INSIDE the confirmed job they were assessed against — never a
flat system-wide list — and each finding carries its evidence, uncertainty,
boundary, practical implication, why-it-matters, and one useful next move.
"""

from __future__ import annotations

import typing
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from tests.capmap.conftest import COLLECTED_AT, contract, one_job_map, two_job_map

from capability_exchange.capmap import CapabilityMap, JobFindings
from capability_exchange.diagnosis import Finding, FoundationCapability
from capability_exchange.jobs import InspectionJob
from capability_exchange.jobs.contract import SuccessContract


def _eight(job_id: str = "weekly-report") -> tuple[Finding, ...]:
    return one_job_map(job_id).jobs[0].findings


class TestFindingsNestInsideJobs:
    def test_the_map_is_organized_around_confirmed_jobs(self) -> None:
        map_ = two_job_map()
        assert [job.job_id for job in map_.jobs] == ["alpha-job", "beta-job"]
        for job in map_.jobs:
            assert isinstance(job.contract, SuccessContract)
            for finding in job.findings:
                assert finding.job_id == job.job_id

    def test_no_flat_system_wide_finding_list_is_representable(self) -> None:
        """The map's only path to a Finding runs through a job entry: no
        CapabilityMap field admits a Finding directly."""
        for name, info in CapabilityMap.model_fields.items():
            assert Finding not in typing.get_args(info.annotation), name
            assert info.annotation is not Finding, name
        jobs_args = typing.get_args(CapabilityMap.model_fields["jobs"].annotation)
        assert JobFindings in jobs_args

    def test_each_finding_carries_the_full_m_d_surface(self) -> None:
        for finding in one_job_map().jobs[0].findings:
            assert hasattr(finding, "evidence")
            assert hasattr(finding, "uncertainty_notes")
            assert hasattr(finding, "safety_boundary")
            assert finding.practical_implication
            assert finding.why_it_matters
            assert finding.recommended_next_move

    def test_why_it_matters_speaks_to_this_jobs_outcome(self) -> None:
        job = one_job_map().jobs[0]
        for finding in job.findings:
            assert job.contract.desired_outcome in finding.why_it_matters


class TestJobEntryShape:
    def test_exactly_one_finding_per_capability(self) -> None:
        job = JobFindings(contract=contract(), findings=_eight())
        assert len(job.findings) == 8
        assert {f.capability for f in job.findings} == set(FoundationCapability)

    def test_a_missing_capability_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="eight Foundation"):
            JobFindings(contract=contract(), findings=_eight()[:7])

    def test_a_doubled_capability_is_rejected(self) -> None:
        eight = _eight()
        with pytest.raises(ValidationError, match="eight Foundation"):
            JobFindings(contract=contract(), findings=(*eight[:7], eight[0]))

    def test_a_finding_never_crosses_between_jobs(self) -> None:
        eight = _eight()
        stray = _eight("another-job")[7]
        with pytest.raises(ValidationError, match="crosses between jobs"):
            JobFindings(contract=contract(), findings=(*eight[:7], stray))

    def test_job_id_is_the_contracts_own(self) -> None:
        job = JobFindings(contract=contract(), findings=_eight())
        assert job.job_id == job.contract.job_id

    def test_an_inspection_draft_cannot_anchor_a_map_entry(self) -> None:
        """R1: only a confirmed Success Contract is representable as the job
        a map entry hangs from — an Inspection-state draft fails validation."""
        draft = InspectionJob(
            job_id="weekly-report",
            title="A draft, not a confirmation",
            situation="Every Friday the status report is due",
            desired_outcome="A finished report the person trusts",
            created_at=COLLECTED_AT,
        )
        with pytest.raises(ValidationError):
            JobFindings(contract=draft, findings=_eight())  # type: ignore[arg-type]


class TestMapShape:
    def test_jobs_are_canonically_ordered(self) -> None:
        zeta = JobFindings(contract=contract("zeta-job"), findings=_eight("zeta-job"))
        alpha = JobFindings(contract=contract("alpha-job"), findings=_eight("alpha-job"))
        map_ = CapabilityMap(assessed_at=COLLECTED_AT, jobs=(zeta, alpha))
        assert [job.job_id for job in map_.jobs] == ["alpha-job", "zeta-job"]

    def test_duplicate_jobs_are_rejected(self) -> None:
        job = JobFindings(contract=contract(), findings=_eight())
        with pytest.raises(ValidationError, match="duplicate"):
            CapabilityMap(assessed_at=COLLECTED_AT, jobs=(job, job))

    def test_an_empty_map_is_unrepresentable(self) -> None:
        with pytest.raises(ValidationError):
            CapabilityMap(assessed_at=COLLECTED_AT, jobs=())

    def test_a_naive_assessment_time_is_rejected(self) -> None:
        job = JobFindings(contract=contract(), findings=_eight())
        with pytest.raises(ValidationError, match="timezone-aware"):
            CapabilityMap(assessed_at=datetime(2026, 8, 7, 12, 0), jobs=(job,))

    def test_job_lookup_refuses_unknown_ids_without_disclosure(self) -> None:
        map_ = one_job_map()
        assert map_.job("weekly-report").job_id == "weekly-report"
        with pytest.raises(KeyError):
            map_.job("never-confirmed")

    def test_the_map_is_frozen_and_closed(self) -> None:
        map_ = one_job_map()
        with pytest.raises(ValidationError):
            map_.assessed_at = datetime(2027, 1, 1, tzinfo=UTC)  # type: ignore[misc]
        payload = {
            "assessed_at": map_.assessed_at,
            "jobs": map_.jobs,
            "overall": "anything",
        }
        with pytest.raises(ValidationError):
            CapabilityMap.model_validate(payload)


class TestValidationBypassRoutes:
    """The map's R1 shape — confirmed contracts only, real findings only —
    must hold on ``model_construct`` / ``model_copy`` too (M2 adversarial
    review; same pattern as EvidenceItem/InspectionJob)."""

    def _draft(self) -> InspectionJob:
        return InspectionJob(
            job_id="draft-job",
            title="A draft",
            situation="Draft situation",
            desired_outcome="Draft outcome",
            created_at=datetime(2026, 8, 7, tzinfo=UTC),
        )

    def test_job_findings_model_construct_rejects_an_inspection_draft(self) -> None:
        real = one_job_map().jobs[0]
        with pytest.raises(ValueError, match="confirmed"):
            JobFindings.model_construct(contract=self._draft(), findings=real.findings)

    def test_job_findings_model_copy_rejects_an_inspection_draft(self) -> None:
        real = one_job_map().jobs[0]
        with pytest.raises(ValueError, match="confirmed"):
            real.model_copy(update={"contract": self._draft()})

    def test_capability_map_model_construct_rejects_non_job_entries(self) -> None:
        map_ = one_job_map()
        with pytest.raises(ValueError, match="JobFindings"):
            CapabilityMap.model_construct(
                assessed_at=map_.assessed_at, jobs=({"looks": "like a job"},)
            )

    def test_model_construct_accepts_the_real_shape(self) -> None:
        map_ = one_job_map()
        rebuilt = CapabilityMap.model_construct(
            assessed_at=map_.assessed_at, jobs=map_.jobs
        )
        assert rebuilt.jobs[0].job_id == map_.jobs[0].job_id
