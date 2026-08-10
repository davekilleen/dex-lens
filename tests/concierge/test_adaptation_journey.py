"""M4 stages 7-8: one bounded adaptation, proof, and undo.

These tests describe the concierge boundary, not the transaction internals.  The
journey owns the state transitions and delegates the actual write to the already
tested adaptation engine; an HTTP handler must never construct or mutate a
transaction itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest
from tests.concierge.test_local_server import RunningServer

from capability_exchange.adaptation.transaction import RecoveryFailedError
from capability_exchange.adapter import (
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.concierge.journey import (
    AdaptationRefusedError,
    ConciergeJourney,
    ConciergeStage,
    ContractFields,
    JobDraftFields,
    JourneyStateError,
    PermissionMetadata,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
SIGNAL = "The local reading list is grouped under topic headings"


def _envelope() -> AdapterResultEnvelope:
    return AdapterResultEnvelope(
        adapter_id="claude-code-local",
        contract_version="1.0.0",
        collected_at=NOW,
        probes=(
            ProbeResult(
                probe_id="reading-list",
                health=InstrumentHealth.HEALTHY,
                evidence=(
                    EvidenceItem(
                        state=EvidenceState.OBSERVED,
                        captured_at=NOW,
                        reference="file:reading-list#snap:test",
                    ),
                ),
            ),
        ),
    )


def _journey(tmp_path: Path, *, situation: str = "When I save useful articles") -> ConciergeJourney:
    root = tmp_path / "claude"
    skills = root / ".claude" / "skills"
    skills.mkdir(parents=True)
    journey = ConciergeJourney(
        permission=PermissionMetadata(
            adapter_id="claude-code-local",
            adapter_version="1.0.0",
            approved_roots=(str(root),),
            approved_artifacts=("reading-list",),
            exclusions=(str(root / ".ssh"),),
            local_only=True,
            offline_capable=True,
            no_catalog=True,
            next_action="Approve read-only inspection",
        ),
        collector=_envelope,
        job_store=tmp_path / "inspection-jobs",
        now=lambda: NOW,
    )
    journey.approve()
    journey.add_job(
        JobDraftFields(
            job_id="reading-list",
            title="Group my reading list",
            situation=situation,
            desired_outcome="My local reading list is grouped by topic",
        )
    )
    journey.select_jobs(("reading-list",))
    journey.confirm_job(
        "reading-list",
        ContractFields(
            success_evidence=(SIGNAL,),
            privacy_limits=("No article text leaves this machine",),
            approval_limits=("Ask before changing my Claude Code setup",),
            autonomy_limits=("Never send or publish the reading list",),
            importance="medium",
            cadence="weekly",
            situation=situation,
            desired_outcome="My local reading list is grouped by topic",
            confirmed_at=NOW,
        ),
    )
    journey.diagnose()
    assert journey.stage is ConciergeStage.CAPABILITY_MAP
    return journey


def _select(journey: ConciergeJourney) -> None:
    root = Path(journey.permission.approved_roots[0])
    journey.select_adaptation(
        job_id="reading-list",
        capability_id="topic-grouping",
        approved_skills_root=root / ".claude" / "skills",
        markdown="# Reading list helper\n\nGroup entries under topic headings.\n",
        expected_benefit="Group new reading-list entries by topic",
        observable_signal=SIGNAL,
    )


def test_one_bounded_adaptation_has_explicit_select_to_undo_stages(tmp_path: Path) -> None:
    journey = _journey(tmp_path)

    _select(journey)
    assert journey.stage is ConciergeStage.ADAPTATION_SELECT

    preview = journey.preview_adaptation()
    assert journey.stage is ConciergeStage.ADAPTATION_PREVIEW
    assert preview.job_id == "reading-list"
    assert preview.prior_state == "absent"

    issued = journey.approve_adaptation()
    assert journey.stage is ConciergeStage.ADAPTATION_APPROVAL
    assert issued.record.preview_digest == preview.preview_digest

    result = journey.apply_adaptation()
    assert journey.stage is ConciergeStage.ADAPTATION_RECEIPT
    assert result.receipt_path.is_file()
    assert Path(preview.target_path).read_text(encoding="utf-8") == preview.content

    verification = journey.verify_adaptation()
    assert journey.stage is ConciergeStage.ADAPTATION_VERIFY
    assert verification.verdict.value == "working"

    undone = journey.undo_adaptation()
    assert journey.stage is ConciergeStage.ADAPTATION_UNDO
    assert undone.status.value == "undone"
    assert not Path(preview.target_path).exists()


def test_high_impact_job_refuses_before_preview_and_says_why(tmp_path: Path) -> None:
    journey = _journey(tmp_path, situation="When I send messages to customers")

    with pytest.raises(AdaptationRefusedError, match="high-impact"):
        _select(journey)

    assert journey.stage is ConciergeStage.ADAPTATION_REFUSED
    assert "high-impact" in journey.adaptation_refusal.lower()
    assert journey.adaptation_preview is None


def test_malformed_selection_refuses_without_creating_a_preview(tmp_path: Path) -> None:
    journey = _journey(tmp_path)
    root = Path(journey.permission.approved_roots[0]) / ".claude" / "skills"
    with pytest.raises(AdaptationRefusedError, match="selection refused"):
        journey.select_adaptation(
            job_id="reading-list",
            capability_id="topic-grouping",
            approved_skills_root=root,
            markdown="",
            expected_benefit="Group the list",
            observable_signal=SIGNAL,
        )
    assert journey.stage is ConciergeStage.ADAPTATION_REFUSED
    assert journey.adaptation_preview is None


def test_unverified_verification_hard_stops_the_session(monkeypatch, tmp_path: Path) -> None:
    journey = _journey(tmp_path)
    _select(journey)
    journey.preview_adaptation()
    journey.approve_adaptation()

    from capability_exchange.adaptation.verification import VerificationResult, VerificationVerdict
    from capability_exchange.diagnosis.finding import CapabilityState
    from capability_exchange.evidence import EvidenceLevel

    unknown = VerificationResult(
        verdict=VerificationVerdict.UNKNOWN,
        capability_state=CapabilityState.UNKNOWN,
        evidence_state=EvidenceState.UNVERIFIED,
        evidence_level=EvidenceLevel.UNKNOWN,
        observable_signal=SIGNAL,
        detail="verification unavailable",
        verified_at=NOW,
    )
    monkeypatch.setattr(
        "capability_exchange.adaptation.transaction.verify_created_skill",
        lambda *args, **kwargs: unknown,
    )

    result = journey.apply_adaptation()
    assert result.hard_stopped
    assert journey.stage is ConciergeStage.ADAPTATION_HARD_STOP
    assert "Unverified" in journey.hard_stop_reason
    with pytest.raises(JourneyStateError, match="hard-stopped"):
        journey.select_adaptation(
            job_id="reading-list",
            capability_id="another-capability",
            approved_skills_root=Path(journey.permission.approved_roots[0]) / ".claude" / "skills",
            markdown="# Another helper\n",
            expected_benefit="A bounded local draft",
            observable_signal=SIGNAL,
        )


def test_recovery_failed_undo_triggers_hard_stop_and_incident(monkeypatch, tmp_path: Path) -> None:
    journey = _journey(tmp_path)
    _select(journey)
    journey.preview_adaptation()
    journey.approve_adaptation()
    journey.apply_adaptation()
    journey.verify_adaptation()

    preview = journey.adaptation_preview
    assert preview is not None
    for manifest in (Path(journey.adaptation_state_root) / "recovery").glob("recovery-*.json"):
        manifest.unlink()

    with pytest.raises(RecoveryFailedError):
        journey.undo_adaptation()
    assert journey.stage is ConciergeStage.ADAPTATION_HARD_STOP
    assert "Recovery failed" in journey.hard_stop_reason
    assert journey.adaptation_incidents


def test_incident_and_hard_stop_runbooks_name_both_fail_closed_triggers() -> None:
    incident = Path("docs/runbooks/incident.md").read_text(encoding="utf-8")
    hard_stop = Path("docs/runbooks/hard-stop.md").read_text(encoding="utf-8")
    for text in (incident, hard_stop):
        assert "Unverified" in text
        assert "Recovery failed" in text
        assert "stop" in text.lower()


def test_http_routes_delegate_the_same_explicit_stages(tmp_path: Path) -> None:
    """Transport routes only invoke domain transitions; they do not mutate inline."""

    with RunningServer(_envelope, approved_root=tmp_path / "claude") as running:
        running.bootstrap()
        running.post("/approve")
        running.wait_for_collection()
        journey = running.session.journey
        journey.add_job(
            JobDraftFields(
                job_id="reading-list",
                title="Group my reading list",
                situation="When I save useful articles",
                desired_outcome="My local reading list is grouped by topic",
            )
        )
        journey.select_jobs(("reading-list",))
        journey.confirm_job(
            "reading-list",
            ContractFields(
                success_evidence=(SIGNAL,),
                privacy_limits=("No article text leaves this machine",),
                approval_limits=("Ask before changing my Claude Code setup",),
                autonomy_limits=("Never send or publish the reading list",),
                importance="medium",
                cadence="weekly",
                confirmed_at=NOW,
            ),
        )
        journey.diagnose()
        skills = running.approved_root / ".claude" / "skills"
        skills.mkdir(parents=True)
        fields = {
            "job_id": "reading-list",
            "capability_id": "topic-grouping",
            "approved_skills_root": str(skills),
            "markdown": "# Reading list helper\n",
            "expected_benefit": "Group entries by topic",
            "observable_signal": SIGNAL,
        }
        status, _, body = running.post("/adaptation/select", urlencode(fields))
        assert status == 200
        assert "Selected adaptation" in body
        for path, expected in (
            ("/adaptation/preview", "Review exact adaptation preview"),
            ("/adaptation/approve", "Adaptation approved"),
            ("/adaptation/apply", "Adaptation receipt"),
            ("/adaptation/verify", "Adaptation verified"),
            ("/adaptation/undo", "Adaptation undone"),
        ):
            status, _, body = running.post(path)
            assert status == 200
            assert expected in body
