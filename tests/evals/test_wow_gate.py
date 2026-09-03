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
            # Both identities, because the ledger's strengths, lessons and
            # connections go on to cite both. A fixture that cites evidence it
            # never records is not an honest ledger, and so cannot show that
            # the grader accepts one.
            evidence_ids=EVIDENCE,
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


UNHELD = ("evidence:sha256:" + "9" * 64, "evidence:sha256:" + "8" * 64)
HELD = "evidence:sha256:" + "7" * 64


def _fabricated_ledger() -> ComparisonLedger:
    """A diagnosis that determined nothing and cites evidence nothing holds.

    This is the ledger an independent review scored at 95/100 through the
    shipped grader on 2026-09-03: every expectation Unknown and evidence-free,
    no observations at all, and every claim citing a fabricated identity.
    """

    insight = GroundedInsight(
        insight_id="connection:invented",
        kind=InsightKind.WORKFLOW_CONNECTION,
        title="Invented connection",
        explanation="Nothing observed supports this.",
        evidence_ids=UNHELD,
        workflow_ids=("workflow:invented",),
    )
    return ComparisonLedger(
        catalogue_version=1,
        catalogue_sha256="a" * 64,
        capabilities=tuple(
            HumanCapability(
                capability_id=f"invented-{index}",
                title=f"Invented capability {index}",
                job_ids=("keep-work-moving",),
                catalogue_ids=(f"invented-{index}",),
                person_observation_ids=(),
            )
            for index in range(1, 8)
        ),
        entries=tuple(
            CatalogueDisposition(
                catalogue_id=f"invented-{index}",
                capability_id=f"invented-{index}",
                disposition=Disposition.WORTH_BORROWING,
                evidence_references=(UNHELD[0],),
                method_compared=True,
                reason=f"Invented reason {index}.",
            )
            for index in range(1, 8)
        ),
        ranked_recommendations=tuple(
            RankedRecommendation(
                catalogue_id=f"invented-{index}",
                capability_id=f"invented-{index}",
                factors=RecommendationFactors(
                    reliability_risk=2,
                    job_relevance=2,
                    workflow_leverage=2,
                    evidence_strength=2,
                    adoption_effort=1,
                ),
                evidence_ids=(UNHELD[0],),
                reason=f"Invented reason {index}.",
                rank=index,
            )
            for index in range(1, 8)
        ),
        reciprocal_answer="No transferable method cleared the evidence bar.",
        expectations=tuple(
            SignificantExpectation(
                family_id=family_id,
                state=ExpectationState.UNKNOWN,
                evidence_ids=(),
                reason=f"Could not determine {family_id}.",
            )
            for family_id in WOW_EXPECTATIONS
        ),
        strengths=(
            GroundedInsight(
                insight_id="strength:invented",
                kind=InsightKind.STRENGTH,
                title="Invented strength",
                explanation="Nothing observed supports this either.",
                evidence_ids=UNHELD,
            ),
        ),
        reciprocal_lessons=(
            GroundedInsight(
                insight_id="lesson:invented",
                kind=InsightKind.RECIPROCAL_LESSON,
                title="Invented lesson",
                explanation="Nothing observed supports this either.",
                evidence_ids=UNHELD,
            ),
        ),
        workflow_insights=(insight,),
        workflow_graph=WorkflowGraph(
            nodes=(
                WorkflowNode(
                    node_id="invented:source",
                    kind=NodeKind.TRIGGER,
                    configuration_state=ConfigurationState.IMPLEMENTED,
                    runtime_state=RuntimeState.OUTCOME_VERIFIED,
                    health_state=HealthState.HEALTHY,
                    evidence_ids=(UNHELD[0],),
                ),
                WorkflowNode(
                    node_id="invented:target",
                    kind=NodeKind.SKILL,
                    configuration_state=ConfigurationState.IMPLEMENTED,
                    runtime_state=RuntimeState.OUTCOME_VERIFIED,
                    health_state=HealthState.HEALTHY,
                    evidence_ids=(UNHELD[1],),
                ),
            ),
            edges=(
                WorkflowEdge(
                    workflow_id="workflow:invented",
                    source_id="invented:source",
                    target_id="invented:target",
                    kind=EdgeKind.CREATES,
                    evidence_ids=UNHELD,
                ),
            ),
        ),
        family_entries=(),
    )


def test_a_diagnosis_that_determined_nothing_does_not_pass() -> None:
    grade = grade_wow_run(_fabricated_ledger(), audit=autonomous_audit())
    assert not grade.passed
    assert grade.score < 90


def test_unknown_and_evidence_free_expectations_score_nothing() -> None:
    grade = grade_wow_run(_fabricated_ledger(), audit=autonomous_audit())
    assert grade.significant_coverage == 0


def test_no_recommendations_scores_nothing() -> None:
    """Producing nothing is not worth eight points."""

    bare = _ledger(rich=True).model_copy(update={"ranked_recommendations": ()})
    assert grade_wow_run(bare, audit=autonomous_audit()).recommendation_quality == 0


def test_a_claim_citing_evidence_the_ledger_does_not_hold_is_a_hard_failure() -> None:
    grade = grade_wow_run(_fabricated_ledger(), audit=autonomous_audit())
    assert "unsupported-claim" in grade.hard_failures


def test_repeating_one_evidence_pair_is_a_single_corroboration() -> None:
    """Handing the same pair to every edge is one corroboration, not many.

    WorkflowEdge.evidence_ids already carries Field(min_length=2), so counting
    edges that clear two ids counts edges. Distinct corroboration is the thing
    worth scoring.
    """

    ledger = _ledger(rich=True)
    one_edge = grade_wow_run(ledger, audit=autonomous_audit()).workflow_quality
    edge = ledger.workflow_graph.edges[0]
    repeated = ledger.model_copy(
        update={
            "workflow_graph": ledger.workflow_graph.model_copy(
                update={
                    "edges": (
                        edge,
                        edge.model_copy(update={"workflow_id": "workflow:second"}),
                        edge.model_copy(update={"workflow_id": "workflow:third"}),
                    )
                }
            )
        }
    )
    assert grade_wow_run(repeated, audit=autonomous_audit()).workflow_quality == one_edge
