"""Automated Wow Gate scoring and hard-failure gates."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    GroundedInsight,
    HumanCapability,
    InsightKind,
)
from capability_exchange.diagnosis.expectations import (
    WOW_EXPECTATIONS,
    ExpectationState,
    SignificantExpectation,
)
from capability_exchange.diagnosis.observations import ConfigurationState, HealthState, RuntimeState
from capability_exchange.diagnosis.ranking import (
    RankedRecommendation,
    RecommendationFactors,
)
from capability_exchange.diagnosis.work import (
    AnalysisMode,
    WorkAudit,
    WorkReceipt,
    WorkStatus,
    queue_digest_for,
)
from capability_exchange.diagnosis.workflows import (
    EdgeKind,
    NodeKind,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from capability_exchange.diagnosis.wow_gate import grade_wow_run

NOW = datetime(2026, 9, 2, tzinfo=UTC)
EVIDENCE = ("evidence:sha256:" + "a" * 64, "evidence:sha256:" + "b" * 64)


def _expectations() -> tuple[SignificantExpectation, ...]:
    return tuple(
        SignificantExpectation(
            family_id=family_id,
            state=ExpectationState.PARTIAL,
            evidence_ids=(EVIDENCE[0],),
            reason=f"Assessed {family_id}.",
        )
        for family_id in WOW_EXPECTATIONS
    )


def _ranked(count: int = 3) -> tuple[RankedRecommendation, ...]:
    return tuple(
        RankedRecommendation(
            catalogue_id=f"capability-{index}",
            capability_id=f"capability-{index}",
            factors=RecommendationFactors(
                reliability_risk=2,
                job_relevance=2,
                workflow_leverage=2,
                evidence_strength=2,
                adoption_effort=1,
            ),
            evidence_ids=(EVIDENCE[0],),
            reason=f"Reason {index}.",
            rank=index,
        )
        for index in range(1, count + 1)
    )


def _ledger(*, rich: bool = False) -> ComparisonLedger:
    ranked = _ranked(3)
    entries = tuple(
        CatalogueDisposition(
            catalogue_id=item.catalogue_id,
            capability_id=item.capability_id,
            disposition=Disposition.WORTH_BORROWING,
            evidence_references=item.evidence_ids,
            method_compared=True,
            reason=item.reason,
        )
        for item in ranked
    )
    strengths = (
        GroundedInsight(
            insight_id="strength:one",
            kind=InsightKind.STRENGTH,
            title="Strong follow-through",
            explanation="Meeting notes become tasks with evidence.",
            evidence_ids=EVIDENCE,
        ),
    )
    lessons = (
        GroundedInsight(
            insight_id="lesson:one",
            kind=InsightKind.RECIPROCAL_LESSON,
            title="Portable review loop",
            explanation="Dex could borrow this weekly review method.",
            evidence_ids=EVIDENCE,
        ),
    )
    workflow_insights = (
        GroundedInsight(
            insight_id="connection:one",
            kind=InsightKind.WORKFLOW_CONNECTION,
            title="Meeting to task bridge",
            explanation="Meetings create tasks that update people context.",
            evidence_ids=EVIDENCE,
            workflow_ids=("workflow:meeting-task",),
        ),
    ) if rich else ()
    graph = WorkflowGraph(
        nodes=(
            WorkflowNode(
                node_id="meeting:processor",
                kind=NodeKind.TRIGGER,
                configuration_state=ConfigurationState.IMPLEMENTED,
                runtime_state=RuntimeState.RECENTLY_RUN,
                health_state=HealthState.HEALTHY,
                evidence_ids=(EVIDENCE[0],),
            ),
            WorkflowNode(
                node_id="task:capturer",
                kind=NodeKind.SKILL,
                configuration_state=ConfigurationState.IMPLEMENTED,
                runtime_state=RuntimeState.OUTCOME_VERIFIED,
                health_state=HealthState.HEALTHY,
                evidence_ids=(EVIDENCE[1],),
            ),
        ),
        edges=(
            WorkflowEdge(
                workflow_id="workflow:meeting-task",
                source_id="meeting:processor",
                target_id="task:capturer",
                kind=EdgeKind.CREATES,
                evidence_ids=EVIDENCE,
            ),
        ),
    ) if rich else WorkflowGraph(nodes=(), edges=())
    return ComparisonLedger(
        catalogue_version=1,
        catalogue_sha256="a" * 64,
        capabilities=tuple(
            HumanCapability(
                capability_id=f"capability-{index}",
                title=f"Capability {index}",
                job_ids=("keep-work-moving",),
                catalogue_ids=(f"capability-{index}",),
                person_observation_ids=(),
            )
            for index in range(1, 4)
        ),
        entries=entries,
        ranked_recommendations=ranked,
        reciprocal_answer="A transferable review method cleared the evidence bar.",
        expectations=_expectations(),
        strengths=strengths,
        reciprocal_lessons=lessons,
        workflow_insights=workflow_insights,
        workflow_graph=graph,
        family_entries=(),
    )


def autonomous_audit() -> WorkAudit:
    packet_ids = tuple(f"packet:sha256:{index:064x}" for index in range(9))
    receipts = tuple(
        WorkReceipt(
            packet_id=packet_id,
            packet_digest=f"sha256:{index + 10:064x}",
            response_digest=f"sha256:{index + 20:064x}",
            status=WorkStatus.COMPLETED,
            attempt_count=1,
            proposal_count=1,
        )
        for index, packet_id in enumerate(packet_ids)
    )
    return WorkAudit(
        mode=AnalysisMode.GUIDED,
        packet_count=9,
        packet_ids=packet_ids,
        queue_digest=queue_digest_for(AnalysisMode.GUIDED, packet_ids),
        completed_count=9,
        unresolved_count=0,
        manual_submission_count=0,
        receipts=receipts,
    )


def audit_with_manual_submission() -> WorkAudit:
    audit = autonomous_audit()
    return SimpleNamespace(
        mode=audit.mode,
        packet_count=audit.packet_count,
        completed_count=audit.completed_count,
        unresolved_count=audit.unresolved_count,
        manual_submission_count=1,
        receipts=audit.receipts,
    )


def high_quality_result() -> ComparisonLedger:
    return _ledger(rich=True)


def rich_result() -> ComparisonLedger:
    return _ledger(rich=True)


def test_high_score_with_manual_proposal_is_a_hard_failure() -> None:
    grade = grade_wow_run(high_quality_result(), audit_with_manual_submission())
    assert grade.score >= 90
    assert grade.passed is False
    assert "manual-proposal" in grade.hard_failures


def test_rich_run_needs_all_expectations_and_a_surprise() -> None:
    grade = grade_wow_run(rich_result(), autonomous_audit())
    assert grade.score >= 90
    assert grade.hard_failures == ()
    assert grade.passed is True


def test_inventory_only_audit_scores_zero_autonomy_points() -> None:
    grade = grade_wow_run(_ledger(), None)
    assert grade.autonomy_and_clarity == 0
