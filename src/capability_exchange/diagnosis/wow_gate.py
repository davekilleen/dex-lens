"""Aggregate Wow Gate scoring and hard-failure evaluation for guided diagnoses."""

from __future__ import annotations

from pydantic import Field

from capability_exchange.diagnosis.comparison import ComparisonLedger, GroundedInsight, InsightKind
from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS, ExpectationState
from capability_exchange.diagnosis.observations import ConfigurationState, HealthState, RuntimeState
from capability_exchange.diagnosis.ranking import MAX_RECOMMENDATIONS
from capability_exchange.diagnosis.run import _ValidatedInventoried
from capability_exchange.diagnosis.work import AnalysisMode, WorkAudit
from capability_exchange.diagnosis.workflows import WorkflowGraph

__all__ = ["WowGrade", "grade_wow_run"]


class WowGrade(_ValidatedInventoried):
    significant_coverage: int = Field(ge=0, le=25)
    workflow_quality: int = Field(ge=0, le=20)
    recommendation_quality: int = Field(ge=0, le=20)
    reciprocal_quality: int = Field(ge=0, le=15)
    evidence_integrity: int = Field(ge=0, le=15)
    autonomy_and_clarity: int = Field(ge=0, le=5)
    hard_failures: tuple[str, ...]

    @property
    def score(self) -> int:
        return (
            self.significant_coverage
            + self.workflow_quality
            + self.recommendation_quality
            + self.reciprocal_quality
            + self.evidence_integrity
            + self.autonomy_and_clarity
        )

    @property
    def passed(self) -> bool:
        return self.score >= 90 and not self.hard_failures


def _insights_have_evidence(
    insights: tuple[GroundedInsight, ...],
) -> bool:
    return all(insight.evidence_ids for insight in insights)


def _workflow_quality(graph: WorkflowGraph) -> int:
    if not graph.edges:
        return 0
    multi_evidence = sum(len(edge.evidence_ids) >= 2 for edge in graph.edges)
    if multi_evidence == 0:
        return 0
    return min(20, 12 + multi_evidence * 4)


def _significant_coverage(expectations: tuple[object, ...]) -> int:
    if not expectations:
        return 0
    if tuple(getattr(item, "family_id", None) for item in expectations) != WOW_EXPECTATIONS:
        return 0
    scored = 0
    for item in expectations:
        state = getattr(item, "state", None)
        if state in {
            ExpectationState.PRESENT,
            ExpectationState.PARTIAL,
            ExpectationState.ABSENT,
            ExpectationState.NOT_RELEVANT,
            ExpectationState.NOT_CURRENTLY_AVAILABLE,
        }:
            scored += 1
        elif state is ExpectationState.UNKNOWN:
            scored += 1
    return min(25, scored * 2 - (1 if scored < len(WOW_EXPECTATIONS) else 0))


def _recommendation_quality(ledger: ComparisonLedger) -> int:
    ranked = ledger.ranked_recommendations
    if not ranked:
        return 8
    if len(ranked) > MAX_RECOMMENDATIONS:
        return 0
    if any(item.rank != index for index, item in enumerate(ranked, start=1)):
        return 0
    if not all(item.evidence_ids and item.factors for item in ranked):
        return 0
    return min(20, 13 + len(ranked))


def _reciprocal_quality(ledger: ComparisonLedger) -> int:
    score = 0
    if ledger.strengths and _insights_have_evidence(ledger.strengths):
        score += 7
    if ledger.reciprocal_lessons and _insights_have_evidence(ledger.reciprocal_lessons):
        score += 8
    return min(15, score)


def _evidence_integrity(ledger: ComparisonLedger) -> int:
    score = 15
    for entry in ledger.local_entries:
        if entry.configuration_state is ConfigurationState.IMPLEMENTED and (
            entry.runtime_state is RuntimeState.OUTCOME_VERIFIED
            or entry.health_state is HealthState.HEALTHY
        ):
            score -= 3
            break
    if not _insights_have_evidence(
        (*ledger.strengths, *ledger.reciprocal_lessons, *ledger.workflow_insights)
    ):
        score = 0
    return max(0, min(15, score))


def _autonomy_and_clarity(audit: WorkAudit | None) -> int:
    if audit is None:
        return 0
    if audit.mode is not AnalysisMode.GUIDED:
        return 0
    if audit.completed_count < audit.packet_count:
        return 1
    if audit.unresolved_count:
        return 2
    return 5


def _hard_failures(ledger: ComparisonLedger, audit: WorkAudit | None) -> tuple[str, ...]:
    failures: list[str] = []
    if audit is not None and audit.manual_submission_count > 0:
        failures.append("manual-proposal")
    if audit is not None and audit.mode is AnalysisMode.GUIDED:
        if audit.completed_count < audit.packet_count:
            failures.append("incomplete-packets")
    if ledger.expectations and tuple(item.family_id for item in ledger.expectations) != (
        WOW_EXPECTATIONS
    ):
        failures.append("missing-expectation")
    elif ledger.family_entries and not ledger.expectations:
        failures.append("missing-expectation")
    if len(ledger.ranked_recommendations) > MAX_RECOMMENDATIONS:
        failures.append("too-many-recommendations")
    if not _insights_have_evidence(
        (*ledger.strengths, *ledger.reciprocal_lessons, *ledger.workflow_insights)
    ):
        failures.append("unsupported-claim")
    for item in ledger.ranked_recommendations:
        if not item.evidence_ids:
            failures.append("unsupported-claim")
            break
    if ledger.workflow_insights and not any(
        item.kind is InsightKind.WORKFLOW_CONNECTION for item in ledger.workflow_insights
    ):
        failures.append("unsupported-claim")
    rich_surprise_required = bool(ledger.workflow_graph.edges) and bool(ledger.expectations)
    if rich_surprise_required and not ledger.workflow_insights:
        failures.append("missing-rich-surprise")
    return tuple(failures)


def grade_wow_run(ledger: ComparisonLedger, audit: WorkAudit | None = None) -> WowGrade:
    """Score one closed diagnosis from typed ledger and audit fields only."""

    hard_failures = _hard_failures(ledger, audit)
    return WowGrade(
        significant_coverage=_significant_coverage(ledger.expectations),
        workflow_quality=_workflow_quality(ledger.workflow_graph),
        recommendation_quality=_recommendation_quality(ledger),
        reciprocal_quality=_reciprocal_quality(ledger),
        evidence_integrity=_evidence_integrity(ledger),
        autonomy_and_clarity=_autonomy_and_clarity(audit),
        hard_failures=hard_failures,
    )
