"""Aggregate Wow Gate scoring and hard-failure evaluation for guided diagnoses.

What this grader can and cannot prove, stated plainly because a score is
easily mistaken for more than it is:

It reads one closed ledger and its audit. It can check that the ledger is
*internally consistent* — that a claim cites evidence the ledger itself
records, that a determinate finding carries evidence, that repeated citation
of one identity is counted once. It cannot check that the evidence is
*authentic*, because a ledger declares its own evidence and the grader never
sees the fingerprint the tokens were minted from. A wholly fabricated but
internally consistent ledger will therefore grade well here.

Authenticity is the engine's job, upstream, where the minted token set is
known. See RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT in docs/RISK-REGISTER.md: while
guided comparison accepts a stored artifact it never re-derives, a passing
grade is not evidence that the conclusions came from the inspected system.
"""

from __future__ import annotations

from pydantic import Field

from capability_exchange.diagnosis.comparison import (
    ComparisonLedger,
    InsightKind,
    ledger_evidence_identities,
)
from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS, ExpectationState
from capability_exchange.diagnosis.payload_guard import (
    HostilePayloadError,
    refuse_hostile_payload,
)
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


def _is_supported(claim: object, held: frozenset[str]) -> bool:
    """A claim is supported when it cites, and cites only, evidence held."""

    cited = {
        *getattr(claim, "evidence_ids", ()),
        *getattr(claim, "observation_ids", ()),
    }
    return bool(cited) and cited <= held


def _supported_fraction(claims: tuple[object, ...], held: frozenset[str]) -> float:
    if not claims:
        return 0.0
    return sum(_is_supported(item, held) for item in claims) / len(claims)


def _all_claims(ledger: ComparisonLedger) -> tuple[object, ...]:
    return (
        *ledger.strengths,
        *ledger.reciprocal_lessons,
        *ledger.workflow_insights,
        *ledger.ranked_recommendations,
        *ledger.expectations,
    )


def _workflow_quality(graph: WorkflowGraph, held: frozenset[str]) -> int:
    """Score distinct corroboration, not edge count.

    ``WorkflowEdge.evidence_ids`` already carries ``Field(min_length=2)``, so
    counting edges that clear two identities counts edges. Handing the same
    pair to every edge is one corroboration however many edges cite it.
    """

    if not graph.edges:
        return 0
    corroborations = {
        frozenset(edge.evidence_ids)
        for edge in graph.edges
        if len(set(edge.evidence_ids)) >= 2 and set(edge.evidence_ids) <= held
    }
    if not corroborations:
        return 0
    return min(20, 12 + len(corroborations) * 4)


_DETERMINATE_STATES = frozenset(
    {
        ExpectationState.PRESENT,
        ExpectationState.PARTIAL,
        ExpectationState.ABSENT,
        ExpectationState.NOT_RELEVANT,
        ExpectationState.NOT_CURRENTLY_AVAILABLE,
    }
)


def _significant_coverage(expectations: tuple[object, ...], held: frozenset[str]) -> int:
    """Score what was determined, not how many rows were emitted.

    ``UNKNOWN`` earns nothing: "we could not tell" is an honest answer but it
    is not coverage. A determinate state earns nothing either unless it cites
    evidence the ledger holds, because a verdict without evidence is a guess
    wearing a verdict's clothes.
    """

    if not expectations:
        return 0
    if tuple(getattr(item, "family_id", None) for item in expectations) != WOW_EXPECTATIONS:
        return 0
    determined = sum(
        1
        for item in expectations
        if getattr(item, "state", None) in _DETERMINATE_STATES and _is_supported(item, held)
    )
    return min(25, round(25 * determined / len(WOW_EXPECTATIONS)))


def _recommendation_quality(ledger: ComparisonLedger, held: frozenset[str]) -> int:
    ranked = ledger.ranked_recommendations
    if not ranked:
        return 0
    if len(ranked) > MAX_RECOMMENDATIONS:
        return 0
    if any(item.rank != index for index, item in enumerate(ranked, start=1)):
        return 0
    if not all(item.factors and _is_supported(item, held) for item in ranked):
        return 0
    return min(20, 13 + len(ranked))


def _reciprocal_quality(ledger: ComparisonLedger, held: frozenset[str]) -> int:
    score = 0
    if ledger.strengths and all(_is_supported(item, held) for item in ledger.strengths):
        score += 7
    if ledger.reciprocal_lessons and all(
        _is_supported(item, held) for item in ledger.reciprocal_lessons
    ):
        score += 8
    return min(15, score)


def _evidence_integrity(ledger: ComparisonLedger, held: frozenset[str]) -> int:
    """Score the proportion of claims whose evidence the ledger actually holds.

    The previous form began at fifteen and only ever deducted three, once, for
    a condition the report renderer uses to mean "working well" — so it was
    either dead or backwards. ``dishonest-operational-state`` is withdrawn
    until it has a definition that distinguishes the two; see the plan at
    docs/superpowers/plans/2026-09-03-dex-lens-trustworthy-first-number.md.
    """

    claims = _all_claims(ledger)
    if not claims:
        return 0
    return max(0, min(15, round(15 * _supported_fraction(claims, held))))


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


def _hard_failures(
    ledger: ComparisonLedger, audit: WorkAudit | None, held: frozenset[str]
) -> tuple[str, ...]:
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
    if any(not _is_supported(item, held) for item in _all_claims(ledger)):
        failures.append("unsupported-claim")
    try:
        refuse_hostile_payload(ledger.model_dump(mode="json"))
    except HostilePayloadError:
        failures.append("private-canary")
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

    held = ledger_evidence_identities(ledger)
    hard_failures = _hard_failures(ledger, audit, held)
    return WowGrade(
        significant_coverage=_significant_coverage(ledger.expectations, held),
        workflow_quality=_workflow_quality(ledger.workflow_graph, held),
        recommendation_quality=_recommendation_quality(ledger, held),
        reciprocal_quality=_reciprocal_quality(ledger, held),
        evidence_integrity=_evidence_integrity(ledger, held),
        autonomy_and_clarity=_autonomy_and_clarity(audit),
        hard_failures=hard_failures,
    )
