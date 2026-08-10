"""M3 guided/export-assisted fallback completion.

The deep adapter can be unavailable before it reads anything.  The fallback
still needs to be a complete local diagnosis journey: bounded person-supplied
evidence, editable Job Map drafts, and a jobs-first Capability Map.  These
tests intentionally use no network or inspected-root writes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest
from tests.concierge.test_local_server import RunningServer, tree_digests

from capability_exchange.adapters.claude_code.containment import ContainmentUnavailableError
from capability_exchange.concierge.journey import (
    CollectionFallback,
    ConciergeJourney,
    ConciergeStage,
    FallbackEvidence,
    FallbackMode,
    PermissionMetadata,
)
from capability_exchange.evidence import EvidenceLevel
from capability_exchange.jobs import InspectionJobStore

NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)


def _permission() -> PermissionMetadata:
    return PermissionMetadata(
        adapter_id="fallback-adapter",
        adapter_version="1.0.0",
        approved_roots=("/tmp/approved",),
        approved_artifacts=("instructions-present",),
        exclusions=("/tmp/approved/.secrets",),
        local_only=True,
        offline_capable=True,
        no_catalog=True,
        next_action="Choose guided or export-assisted evidence",
    )


def _fallback() -> CollectionFallback:
    return CollectionFallback(
        mode=FallbackMode.GUIDED,
        reason="containment unavailable; no direct inspection was performed",
    )


def test_guided_fallback_can_be_completed_into_job_map_and_capability_map(
    tmp_path: Path,
) -> None:
    journey = ConciergeJourney(
        permission=_permission(),
        collector=_fallback,
        job_store=InspectionJobStore(tmp_path / "jobs"),
        now=lambda: NOW,
    )

    journey.approve()
    assert journey.stage is ConciergeStage.FALLBACK
    journey.add_fallback_evidence(
        FallbackEvidence(
            label="recent activity",
            level=EvidenceLevel.SUPPORTED,
            detail="A bounded export describes a recent review",
            reference="export:recent-review#sha256=abc123",
            probe_id="recent-activity",
        )
    )
    journey.continue_fallback()
    assert journey.stage is ConciergeStage.JOB_MAP
    assert journey.envelope is not None
    assert all(
        item.state.value != "observed"
        for probe in journey.envelope.probes
        for item in probe.evidence
    )

    draft = journey.add_job(
        title="My bounded review",
        situation="When I review the export",
        desired_outcome="The review has one clear next action",
    )
    discarded = journey.add_job(
        title="Temporary review",
        situation="While testing the fallback",
        desired_outcome="The temporary draft can be removed",
    )
    edited = journey.edit_job(
        discarded.job_id,
        title="Edited temporary review",
        situation="After reviewing the fallback",
        desired_outcome="The edited draft can still be removed",
    )
    assert edited.title == "Edited temporary review"
    journey.discard_job(discarded.job_id)
    assert discarded.job_id not in journey.job_ids
    journey.confirm_job(
        draft.job_id,
        success_evidence=("the next action is recorded",),
        privacy_limits=("stay within the supplied export",),
        approval_limits=("ask before any external action",),
        autonomy_limits=("do not change files",),
        importance="medium",
        cadence="weekly",
        confirmed_at=NOW,
    )

    capability_map = journey.diagnose()
    assert journey.stage is ConciergeStage.CAPABILITY_MAP
    assert capability_map.jobs[0].job_id == draft.job_id


def test_fallback_rejects_raw_or_unbounded_import_without_losing_previous_items(
    tmp_path: Path,
) -> None:
    journey = ConciergeJourney(
        permission=_permission(),
        collector=_fallback,
        job_store=InspectionJobStore(tmp_path / "jobs"),
        now=lambda: NOW,
    )
    journey.approve()
    journey.add_fallback_evidence(
        FallbackEvidence(
            label="known",
            level=EvidenceLevel.REPORTED,
            detail="I described the bounded behavior",
            reference="account:person-report-1",
        )
    )

    with pytest.raises(ValueError, match="reference|bounded|payload"):
        journey.import_fallback_evidence(
            "known|supported|-----BEGIN PRIVATE KEY-----|raw material"
        )
    assert len(journey.fallback.evidence) == 1  # type: ignore[union-attr]


def test_unknown_import_may_omit_a_source_reference(tmp_path: Path) -> None:
    journey = ConciergeJourney(
        permission=_permission(),
        collector=_fallback,
        job_store=InspectionJobStore(tmp_path / "jobs"),
        now=lambda: NOW,
    )
    journey.approve()
    imported = journey.import_fallback_evidence("missing|unknown||not supplied")
    assert imported[0].level is EvidenceLevel.UNKNOWN


def test_http_fallback_reaches_capability_map_without_root_write_or_verified_label(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    (root / "sentinel.txt").write_text("do not touch", encoding="utf-8")
    before = tree_digests(root)

    def unavailable(_cancel_event: object) -> object:
        raise ContainmentUnavailableError("sandbox unavailable")

    with RunningServer(unavailable, approved_root=root) as running:
        running.bootstrap()
        status, _, body = running.post("/approve")
        assert status == 200
        assert "guided" in body.lower()
        assert "Capability Map" not in body
        assert all(label not in body for label in ("Verified", "verified"))

        status, _, body = running.post(
            "/fallback/evidence",
            body=urlencode(
                {
                    "mode": "export-assisted",
                    "label": "recent activity",
                    "level": "supported",
                    "reference": "export:review#sha256=abc123",
                    "probe_id": "recent-activity",
                    "detail": "A bounded export describes recent work",
                }
            ),
        )
        assert status == 200
        assert "Supported" in body
        assert "verified" not in body.lower()

        status, _, body = running.post("/fallback/continue")
        assert status == 200
        assert "Confirm your Job Map" in body

        status, _, body = running.post(
            "/jobs/add",
            body=urlencode(
                {
                    "title": "Review supplied evidence",
                    "situation": "When I review the supplied export",
                    "desired_outcome": "The review has a clear next action",
                }
            ),
        )
        assert status == 200
        job_id = running.session.journey.job_ids[0]
        status, _, body = running.post(
            "/jobs/confirm",
            body=urlencode(
                {
                    "job_id": job_id,
                    "success_evidence": "the next action is recorded",
                    "privacy_limits": "stay within the supplied export",
                    "approval_limits": "ask before external action",
                    "autonomy_limits": "do not change files",
                    "importance": "medium",
                    "cadence": "weekly",
                }
            ),
        )
        assert status == 200
        status, _, body = running.post("/diagnose")
        assert status == 200
        assert "Capability Map" in body
        assert "verified" not in body.lower()

    assert tree_digests(root) == before
