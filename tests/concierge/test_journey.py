"""M3 journey/domain/view contract tests.

The tests deliberately exercise the product boundary rather than the HTTP
transport.  ``server.py`` can bind these narrow operations later without
having to recreate Job Map or diagnosis rules in request handlers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_exchange.adapter import (
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.concierge.journey import (
    CollectionFallback,
    ConciergeJourney,
    ConciergeStage,
    ContractFields,
    FallbackEvidence,
    FallbackMode,
    JobDraftFields,
    JourneyStateError,
    PermissionMetadata,
)
from capability_exchange.concierge.views import (
    render_fallback,
    render_job_map,
    render_permission,
)
from capability_exchange.evidence import EvidenceItem, EvidenceLevel, EvidenceState
from capability_exchange.jobs import InspectionJobStore, SuccessContract

NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)


def _envelope() -> AdapterResultEnvelope:
    return AdapterResultEnvelope(
        adapter_id="test-adapter",
        contract_version="1.2.3",
        collected_at=NOW,
        probes=(
            ProbeResult(
                probe_id="instructions-present",
                health=InstrumentHealth.HEALTHY,
                evidence=(
                    EvidenceItem(
                        state=EvidenceState.OBSERVED,
                        captured_at=NOW,
                        reference="file:instructions#snap:abc123",
                    ),
                ),
            ),
        ),
    )


def _permission() -> PermissionMetadata:
    return PermissionMetadata(
        adapter_id="test-adapter",
        adapter_version="1.2.3",
        approved_roots=("/tmp/approved",),
        approved_artifacts=("instructions-present",),
        exclusions=("/tmp/approved/.credentials", "~/.ssh"),
        local_only=True,
        offline_capable=True,
        no_catalog=True,
        next_action="Approve this read-only inspection",
    )


def _journey(tmp_path: Path, *, collector=None) -> ConciergeJourney:
    return ConciergeJourney(
        permission=_permission(),
        collector=collector or _envelope,
        job_store=InspectionJobStore(tmp_path),
        now=lambda: NOW,
    )


def _contract_fields() -> ContractFields:
    return ContractFields(
        success_evidence=("the instruction-guided output is ready",),
        privacy_limits=("never read the private journal",),
        approval_limits=("ask before any external action",),
        autonomy_limits=("do not change files autonomously",),
        importance="medium",
        cadence="weekly",
        confirmed_at=NOW,
    )


class TestPermissionAndStages:
    def test_permission_metadata_names_the_full_boundary(self) -> None:
        metadata = _permission()
        assert metadata.adapter_id == "test-adapter"
        assert metadata.adapter_version == "1.2.3"
        assert metadata.approved_roots == ("/tmp/approved",)
        assert metadata.approved_artifacts == ("instructions-present",)
        assert metadata.exclusions == ("/tmp/approved/.credentials", "~/.ssh")
        assert metadata.local_only is True
        assert metadata.offline_capable is True
        assert metadata.no_catalog is True
        assert metadata.next_action

    def test_no_collection_before_explicit_permission(self, tmp_path: Path) -> None:
        calls: list[str] = []

        def collect() -> AdapterResultEnvelope:
            calls.append("read")
            return _envelope()

        journey = _journey(tmp_path, collector=collect)
        assert journey.stage is ConciergeStage.PERMISSION
        assert calls == []
        assert journey.envelope is None

        journey.approve()
        assert calls == ["read"]
        assert journey.stage is ConciergeStage.JOB_MAP

    def test_permission_view_is_unscanned_local_and_escaped(self) -> None:
        metadata = PermissionMetadata(
            adapter_id="adapter-<x>",
            adapter_version="1.2.3",
            approved_roots=("/tmp/<approved>",),
            approved_artifacts=("artifact-<x>",),
            exclusions=("/secret<&",),
            local_only=True,
            offline_capable=True,
            no_catalog=True,
            next_action="Approve <read-only>",
        )
        page = render_permission(metadata, csrf_token="csrf<&")
        assert "adapter-&lt;x&gt;" in page
        assert "/tmp/&lt;approved&gt;" in page
        assert "artifact-&lt;x&gt;" in page
        assert "/secret&lt;&amp;" in page
        assert 'name="csrf_token" value="csrf&lt;&amp;"' in page
        assert "Nothing has been read" in page
        assert "<script" not in page.lower()
        assert "https://" not in page.lower()
        for forbidden in ("localStorage", "fetch(", "websocket", "analytics"):
            assert forbidden.lower() not in page.lower()


class TestJobMapPersistence:
    def test_proposals_are_persisted_as_inspection_jobs(self, tmp_path: Path) -> None:
        journey = _journey(tmp_path)
        journey.approve()
        assert journey.job_ids == ("instruction-guided-work",)
        draft = journey.job_store.load("instruction-guided-work")
        assert draft.lifecycle == "inspection"
        assert journey.stage is ConciergeStage.JOB_MAP

    def test_manual_add_edit_and_discard_use_the_store(self, tmp_path: Path) -> None:
        journey = _journey(tmp_path)
        journey.approve()
        manual = journey.add_job(
            JobDraftFields(
                job_id="manual-weekly-review",
                title="My weekly review",
                situation="At the end of each week",
                desired_outcome="The review has a clear next action",
            )
        )
        assert manual.job_id in journey.job_ids
        edited = journey.edit_job(
            manual.job_id,
            JobDraftFields(
                job_id=manual.job_id,
                title="My edited weekly review",
                situation="On Friday afternoon",
                desired_outcome="The review has one clear next action",
            ),
        )
        assert edited.title == "My edited weekly review"
        journey.discard_job(manual.job_id)
        assert manual.job_id not in journey.job_ids

    def test_manual_id_collision_refuses_without_overwriting(self, tmp_path: Path) -> None:
        journey = _journey(tmp_path)
        journey.approve()
        original = journey.job_store.load("instruction-guided-work")

        with pytest.raises(JourneyStateError, match="already exists"):
            journey.add_job(
                JobDraftFields(
                    job_id="instruction-guided-work",
                    title="Replacement",
                    situation="A conflicting request",
                    desired_outcome="The old draft would be lost",
                )
            )

        assert journey.job_store.load("instruction-guided-work") == original

    def test_job_map_view_has_csrf_on_local_forms_and_escapes_text(self, tmp_path: Path) -> None:
        journey = _journey(tmp_path)
        journey.approve()
        page = render_job_map(journey.inspection_jobs, csrf_token="token<&")
        assert 'name="csrf_token" value="token&lt;&amp;"' in page
        assert "Possible job" in page
        assert "<script" not in page.lower()
        assert "https://" not in page.lower()


class TestFullConfirmationAndDiagnosis:
    def test_invalid_confirmation_leaves_draft_bytes_intact(self, tmp_path: Path) -> None:
        journey = _journey(tmp_path)
        journey.approve()
        path = journey.job_store.directory / "inspection-job-instruction-guided-work.json"
        assert path.exists()
        with pytest.raises(ValidationError):
            journey.confirm_job(
                "instruction-guided-work",
                ContractFields(
                    success_evidence=(),
                    privacy_limits=("private",),
                    approval_limits=("ask",),
                    autonomy_limits=("none",),
                    importance="medium",
                    cadence="weekly",
                    confirmed_at=NOW,
                ),
            )
        assert path.exists()
        assert journey.job_store.load("instruction-guided-work").lifecycle == "inspection"

    def test_confirm_requires_full_user_contract_and_deletes_draft(self, tmp_path: Path) -> None:
        journey = _journey(tmp_path)
        journey.approve()
        contract = journey.confirm_job("instruction-guided-work", _contract_fields())
        assert type(contract) is SuccessContract
        assert contract.success_evidence == ("the instruction-guided output is ready",)
        assert contract.boundaries.approval_limits == ("ask before any external action",)
        assert journey.job_store.job_ids() == ()

    def test_diagnosis_is_refused_until_all_selected_jobs_confirmed(self, tmp_path: Path) -> None:
        journey = _journey(tmp_path)
        journey.approve()
        journey.add_job(
            JobDraftFields(
                job_id="manual-review",
                title="Manual review",
                situation="When work is ready",
                desired_outcome="A review decision is recorded",
            )
        )
        journey.confirm_job("instruction-guided-work", _contract_fields())
        with pytest.raises(JourneyStateError):
            journey.diagnose()
        assert journey.job_store.job_ids() == ("manual-review",)

        journey.confirm_job("manual-review", _contract_fields())
        capability_map = journey.diagnose()
        assert journey.stage is ConciergeStage.CAPABILITY_MAP
        assert tuple(job.contract.job_id for job in capability_map.jobs) == (
            "instruction-guided-work",
            "manual-review",
        )
        assert "Your job: instruction-guided-work" in journey.capability_map_markdown

    def test_close_cleans_up_at_every_stage(self, tmp_path: Path) -> None:
        journey = _journey(tmp_path)
        journey.close()
        assert journey.stage is ConciergeStage.CLOSED
        assert journey.envelope is None
        assert journey.job_ids == ()

        journey = _journey(tmp_path / "second")
        journey.approve()
        assert journey.job_ids
        journey.close()
        assert journey.stage is ConciergeStage.CLOSED
        assert journey.job_ids == ()
        assert list((tmp_path / "second").glob("inspection-job-*.json")) == []


class TestFallbackViews:
    def test_fallback_labels_only_supported_reported_unknown(self) -> None:
        fallback = CollectionFallback(
            mode=FallbackMode.EXPORT_ASSISTED,
            reason="The deep adapter is unavailable on this host.",
            evidence=(
                FallbackEvidence("config", EvidenceLevel.SUPPORTED, "an export you supplied"),
                FallbackEvidence("account", EvidenceLevel.REPORTED, "your description"),
                FallbackEvidence("missing", EvidenceLevel.UNKNOWN, "not provided"),
            ),
        )
        page = render_fallback(fallback, csrf_token="csrf")
        assert "Supported" in page
        assert "Reported" in page
        assert "Unknown" in page
        assert "Verified" not in page
        assert 'name="csrf_token" value="csrf"' in page
        assert "<script" not in page.lower()

    def test_fallback_never_downgrades_to_a_verified_claim(self) -> None:
        fallback = CollectionFallback(
            mode=FallbackMode.GUIDED,
            reason="No deep adapter.",
            evidence=(FallbackEvidence("claim", EvidenceLevel.VERIFIED, "bad"),),
        )
        page = render_fallback(fallback, csrf_token="csrf")
        assert "Verified" not in page
        assert "Unknown" in page
