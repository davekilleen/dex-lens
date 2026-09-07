"""Automated Wow Gate scoring and hard-failure gates."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    FamilyLedgerEntry,
    GroundedInsight,
    HumanCapability,
    InsightKind,
)
from capability_exchange.diagnosis.expectations import (
    NOT_GATED_REASON,
    WOW_EXPECTATIONS,
    ExpectationState,
    SignificantExpectation,
)
from capability_exchange.diagnosis.families import FamilyAvailability
from capability_exchange.diagnosis.observations import ConfigurationState, HealthState, RuntimeState
from capability_exchange.diagnosis.ranking import (
    RankedRecommendation,
    RecommendationFactors,
)
from capability_exchange.diagnosis.significant_families import FamilyAssessmentDisposition
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


def _ledger(*, rich: bool = False, audit: WorkAudit | None = None) -> ComparisonLedger:
    """A closed ledger carrying the audit it was closed with, as the engine does."""

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
        work_audit=audit if audit is not None else autonomous_audit(),
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


def high_quality_result() -> ComparisonLedger:
    return _ledger(rich=True)


def rich_result() -> ComparisonLedger:
    return _ledger(rich=True)


def test_rich_run_needs_all_expectations_and_a_surprise() -> None:
    grade = grade_wow_run(rich_result(), autonomous_audit())
    assert grade.score >= 90
    assert grade.hard_failures == ()
    assert grade.passed is True


def inventory_only_audit() -> WorkAudit:
    return WorkAudit(
        mode=AnalysisMode.INVENTORY_ONLY,
        packet_count=0,
        packet_ids=(),
        queue_digest=queue_digest_for(AnalysisMode.INVENTORY_ONLY, ()),
        completed_count=0,
        unresolved_count=0,
        manual_submission_count=0,
        receipts=(),
    )


def test_inventory_only_audit_scores_zero_autonomy_points() -> None:
    grade = grade_wow_run(_ledger(audit=inventory_only_audit()))
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
        work_audit=autonomous_audit(),
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


def test_grading_uses_the_audit_bound_into_the_ledger() -> None:
    """The audit that counts is the one the ledger was closed with.

    A separate file is not evidence about this run: it can be another run's
    audit, or hand-written. The ledger carries its audit inside the canonical
    payload and the digest, so that is the one to grade.
    """

    bound = autonomous_audit()
    ledger = _ledger(rich=True).model_copy(update={"work_audit": bound})
    assert grade_wow_run(ledger).autonomy_and_clarity == 5


def _another_runs_audit() -> WorkAudit:
    """A valid audit from a different run: different packets, same shape."""

    packet_ids = tuple(f"packet:sha256:{index + 100:064x}" for index in range(9))
    receipts = tuple(
        WorkReceipt(
            packet_id=packet_id,
            packet_digest=f"sha256:{index + 110:064x}",
            response_digest=f"sha256:{index + 120:064x}",
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


def test_grading_refuses_an_audit_that_is_not_this_ledgers() -> None:
    """Grading run A's ledger against run B's clean audit must not be possible."""

    ledger = _ledger(rich=True).model_copy(update={"work_audit": autonomous_audit()})
    with pytest.raises(ValueError, match="does not belong"):
        grade_wow_run(ledger, audit=_another_runs_audit())


def _family_free_not_gated_rows() -> tuple[SignificantExpectation, ...]:
    """The loud manifest a family-free catalogue must now yield."""

    from tests.diagnosis.test_significant_family_assessment import _catalogue

    from capability_exchange.diagnosis.expectations import assess_wow_expectations

    return assess_wow_expectations(_catalogue(), ())


def test_absent_expectations_on_a_family_free_ledger_is_a_hard_failure() -> None:
    """An empty expectation manifest can never again pass silently.

    Observed failing on the unchanged tree: a family-free ledger with
    ``expectations == ()`` graded with no ``missing-expectation`` failure —
    exactly the first real run's silent hole.
    """

    ledger = _ledger(rich=True).model_copy(update={"expectations": ()})
    grade = grade_wow_run(ledger, audit=autonomous_audit())

    assert "missing-expectation" in grade.hard_failures
    assert grade.passed is False


def test_a_loud_not_gated_manifest_is_accepted_at_zero_coverage() -> None:
    """Fourteen explicit not-gated rows are honest, scoreless, and lawful.

    Observed failing on the unchanged tree: ``assess_wow_expectations``
    returned an empty tuple for a family-free catalogue, so the rows below did
    not exist at all.
    """

    rows = _family_free_not_gated_rows()
    assert len(rows) == 14
    assert all(item.state.value == "not-gated" for item in rows)

    ledger = _ledger(rich=True).model_copy(update={"expectations": rows})
    grade = grade_wow_run(ledger, audit=autonomous_audit())

    assert "missing-expectation" not in grade.hard_failures
    assert "unsupported-claim" not in grade.hard_failures
    assert grade.significant_coverage == 0


def test_the_family_carrying_path_is_unchanged_by_the_not_gated_state() -> None:
    """Determinate gated rows keep exactly their previous coverage score."""

    grade = grade_wow_run(_ledger(rich=True), audit=autonomous_audit())
    assert grade.significant_coverage == 25
    assert grade.hard_failures == ()


# ---------------------------------------------------------------------------
# The two-pass gate: pass-1 completeness graded separately from pass-2 depth.
# Every failure class and sub-score below was observed failing/absent on the
# unchanged tree first (design item 9, 2026-09-07).
# ---------------------------------------------------------------------------

_SELECTED = (
    "backup-and-restore-confidence",
    "durable-work-memory",
    "proactive-health-and-recovery",
)
_UNSELECTED = tuple(sorted(set(WOW_EXPECTATIONS) - set(_SELECTED)))
_MEMBERS = {
    "backup-and-restore-confidence": ("backup-now", "backup-restore"),
    "durable-work-memory": ("memory-log", "memory-search"),
    "proactive-health-and-recovery": ("health-watch", "recovery-proof"),
}
_PRICED_REASON = "Not selected for this focused run; a follow-up dive would settle it."
_SILENT_REASON = "No specialist proposal cleared the evidence bar."


def _focused_audit(*, completed: int = 9) -> WorkAudit:
    packet_ids = tuple(f"packet:sha256:{index + 200:064x}" for index in range(9))
    receipts = tuple(
        WorkReceipt(
            packet_id=packet_id,
            packet_digest=f"sha256:{index + 210:064x}",
            response_digest=f"sha256:{index + 220:064x}",
            status=WorkStatus.COMPLETED,
            attempt_count=1,
            proposal_count=1,
        )
        for index, packet_id in enumerate(packet_ids[:completed])
    )
    return WorkAudit(
        mode=AnalysisMode.FOCUSED,
        packet_count=9,
        packet_ids=packet_ids,
        queue_digest=queue_digest_for(AnalysisMode.FOCUSED, packet_ids),
        completed_count=completed,
        unresolved_count=0,
        manual_submission_count=0,
        receipts=receipts,
    )


def _focused_expectations() -> tuple[SignificantExpectation, ...]:
    """Selected families determinate with held evidence; the rest loud, priced."""

    return tuple(
        SignificantExpectation(
            family_id=family_id,
            state=ExpectationState.PARTIAL,
            evidence_ids=(EVIDENCE[0],),
            reason=f"Assessed {family_id}.",
        )
        if family_id in _SELECTED
        else SignificantExpectation(
            family_id=family_id,
            state=ExpectationState.UNKNOWN,
            evidence_ids=(),
            reason=_PRICED_REASON,
        )
        for family_id in WOW_EXPECTATIONS
    )


def _focused_family_entries() -> tuple[FamilyLedgerEntry, ...]:
    return tuple(
        FamilyLedgerEntry(
            family_id=family_id,
            title=f"Family {family_id}",
            outcome="The signed outcome this family exists to deliver.",
            signed_availability=FamilyAvailability.AVAILABLE,
            available_member_ids=_MEMBERS[family_id],
            unavailable_member_ids=(),
            recommendable_member_ids=_MEMBERS[family_id],
            matched_components=(),
            matched_observation_ids=(),
            unresolved_components=(),
            evidence_references=(),
            disposition=FamilyAssessmentDisposition.UNRESOLVED,
            reason="No exact supported local evidence matched this signed family.",
        )
        for family_id in _SELECTED
    )


def _member_entries(*, silent_member: str | None = None) -> tuple[CatalogueDisposition, ...]:
    """Selected-family member verdicts; ``health-watch`` is a LOUD could-not-tell.

    A loud not-assessed row carries the dispute's evidence and reason, exactly
    as ``_entry_for`` records a disputed candidate.  A silent one carries
    neither — it was simply never proposed.
    """

    entries: list[CatalogueDisposition] = []
    for family_id in _SELECTED:
        for member_id in _MEMBERS[family_id]:
            if member_id == silent_member:
                entries.append(
                    CatalogueDisposition(
                        catalogue_id=member_id,
                        capability_id=member_id,
                        disposition=Disposition.NOT_ASSESSED,
                        reason=_SILENT_REASON,
                    )
                )
            elif member_id == "health-watch":
                entries.append(
                    CatalogueDisposition(
                        catalogue_id=member_id,
                        capability_id=member_id,
                        disposition=Disposition.NOT_ASSESSED,
                        evidence_references=(EVIDENCE[1],),
                        reason="Specialists disagreed; the dispute is recorded with evidence.",
                    )
                )
            else:
                entries.append(
                    CatalogueDisposition(
                        catalogue_id=member_id,
                        capability_id=member_id,
                        disposition=Disposition.STRONG_HERE,
                        evidence_references=(EVIDENCE[0],),
                        reason=f"Verified locally: {member_id} runs and is current.",
                    )
                )
    return tuple(entries)


def _honest_focused_ledger(
    *, silent_member: str | None = None, audit: WorkAudit | None = None
) -> ComparisonLedger:
    base = _ledger(rich=True)
    return base.model_copy(
        update={
            "entries": (*base.entries, *_member_entries(silent_member=silent_member)),
            "family_entries": _focused_family_entries(),
            "expectations": _focused_expectations(),
            "focus_selected_family_ids": _SELECTED,
            "focus_unselected_family_ids": _UNSELECTED,
            "work_audit": audit if audit is not None else _focused_audit(),
        }
    )


def _hollow_focused_ledger() -> ComparisonLedger:
    """Shape-perfect and evidence-free: the register reproduction, focused.

    Every expectation is a nicely rendered Unknown, every selected-family
    member sits silently not-assessed, and every insight cites evidence the
    ledger never records.  The 2026-09-03 review's fabricated ledger scored 95
    through the shipped grader; this is its spirit re-run against the two-pass
    product.
    """

    return ComparisonLedger(
        catalogue_version=1,
        catalogue_sha256="a" * 64,
        capabilities=(),
        entries=tuple(
            CatalogueDisposition(
                catalogue_id=member_id,
                capability_id=member_id,
                disposition=Disposition.NOT_ASSESSED,
                reason=_SILENT_REASON,
            )
            for family_id in _SELECTED
            for member_id in _MEMBERS[family_id]
        ),
        ranked_recommendations=(),
        reciprocal_answer="No transferable method cleared the evidence bar.",
        expectations=tuple(
            SignificantExpectation(
                family_id=family_id,
                state=ExpectationState.UNKNOWN,
                evidence_ids=(),
                reason=f"Could not determine {family_id} from the snapshot.",
            )
            for family_id in WOW_EXPECTATIONS
        ),
        strengths=(
            GroundedInsight(
                insight_id="strength:hollow",
                kind=InsightKind.STRENGTH,
                title="Invented strength",
                explanation="Nothing recorded supports this.",
                evidence_ids=UNHELD,
            ),
        ),
        reciprocal_lessons=(
            GroundedInsight(
                insight_id="lesson:hollow",
                kind=InsightKind.RECIPROCAL_LESSON,
                title="Invented lesson",
                explanation="Nothing recorded supports this either.",
                evidence_ids=UNHELD,
            ),
        ),
        workflow_insights=(),
        workflow_graph=WorkflowGraph(nodes=(), edges=()),
        family_entries=_focused_family_entries(),
        focus_selected_family_ids=_SELECTED,
        focus_unselected_family_ids=_UNSELECTED,
        work_audit=_focused_audit(),
    )


def _with_expectation(
    ledger: ComparisonLedger, row: SignificantExpectation
) -> ComparisonLedger:
    rows = tuple(
        row if item.family_id == row.family_id else item for item in ledger.expectations
    )
    return ledger.model_copy(update={"expectations": rows})


def test_an_unpriced_unknown_is_a_hard_failure() -> None:
    """An Unknown whose reason is not a rendered sentence fails the gate.

    Observed absent on the unchanged tree: the row below (held evidence, so no
    unsupported-claim fires) graded with zero hard failures.
    """

    ledger = _with_expectation(
        _ledger(rich=True),
        SignificantExpectation(
            family_id="career-growth-evidence",
            state=ExpectationState.UNKNOWN,
            evidence_ids=(EVIDENCE[0],),
            reason="unknown",
        ),
    )
    grade = grade_wow_run(ledger, audit=autonomous_audit())
    assert "unpriced-unknown" in grade.hard_failures
    assert grade.passed is False


def test_a_loudly_priced_unknown_is_lawful_without_evidence() -> None:
    """An honest could-not-tell with its reason sentence rendered fails nothing.

    Observed failing on the unchanged tree: the evidence-free Unknown row was
    counted as an unsupported claim, punishing exactly the loudness the
    two-pass product demands.
    """

    ledger = _with_expectation(
        _ledger(rich=True),
        SignificantExpectation(
            family_id="career-growth-evidence",
            state=ExpectationState.UNKNOWN,
            evidence_ids=(),
            reason="Nothing in the approved snapshot reached this area; a focused dive would.",
        ),
    )
    grade = grade_wow_run(ledger, audit=autonomous_audit())
    assert "unsupported-claim" not in grade.hard_failures
    assert "unpriced-unknown" not in grade.hard_failures


def test_an_unknown_citing_evidence_the_ledger_lacks_is_still_unsupported() -> None:
    """Fabricated support on an Unknown row stays a hard failure."""

    ledger = _with_expectation(
        _ledger(rich=True),
        SignificantExpectation(
            family_id="career-growth-evidence",
            state=ExpectationState.UNKNOWN,
            evidence_ids=(UNHELD[0],),
            reason="Nothing in the approved snapshot reached this area; a focused dive would.",
        ),
    )
    grade = grade_wow_run(ledger, audit=autonomous_audit())
    assert "unsupported-claim" in grade.hard_failures


def test_a_tampered_not_gated_row_is_a_hard_failure() -> None:
    """Not-gated is lawful only as the full loud manifest with the fixed sentence.

    Observed absent on the unchanged tree: both manifests below graded with no
    ``unpriced-unknown`` failure.
    """

    reworded = _ledger(rich=True).model_copy(
        update={
            "expectations": tuple(
                SignificantExpectation(
                    family_id=family_id,
                    state=ExpectationState.NOT_GATED,
                    evidence_ids=(),
                    reason="Tampered placeholder.",
                )
                for family_id in WOW_EXPECTATIONS
            )
        }
    )
    assert "unpriced-unknown" in grade_wow_run(reworded, audit=autonomous_audit()).hard_failures

    partially_gated = _with_expectation(
        _ledger(rich=True),
        SignificantExpectation(
            family_id="career-growth-evidence",
            state=ExpectationState.NOT_GATED,
            evidence_ids=(),
            reason=NOT_GATED_REASON,
        ),
    )
    grade = grade_wow_run(partially_gated, audit=autonomous_audit())
    assert "unpriced-unknown" in grade.hard_failures


def test_pass_one_completeness_is_graded_separately_from_depth() -> None:
    """The pass-1 sub-score counts loud-or-determinate rows out of fourteen.

    Observed absent on the unchanged tree: ``WowGrade`` had no
    ``pass_one_completeness`` field at all.
    """

    complete = grade_wow_run(_ledger(rich=True), audit=autonomous_audit())
    assert complete.pass_one_completeness == 14

    holed = _with_expectation(
        _ledger(rich=True),
        SignificantExpectation(
            family_id="career-growth-evidence",
            state=ExpectationState.UNKNOWN,
            evidence_ids=(EVIDENCE[0],),
            reason="unknown",
        ),
    )
    grade = grade_wow_run(holed, audit=autonomous_audit())
    assert grade.pass_one_completeness == 13
    assert grade.passed is False


def test_a_silent_not_assessed_member_in_a_selected_family_hard_fails() -> None:
    """The gate-level mirror of the engine's focused-coverage close rule.

    Observed absent on the unchanged tree: this ledger graded with no
    ``sampled-selection`` failure.
    """

    sampled = _honest_focused_ledger(silent_member="backup-restore")
    grade = grade_wow_run(sampled)
    assert "sampled-selection" in grade.hard_failures
    assert grade.passed is False


def test_a_selected_family_missing_its_ledger_row_is_sampling() -> None:
    """Dropping a selected family's row cannot hide its silent members."""

    tampered = _honest_focused_ledger().model_copy(
        update={"family_entries": _focused_family_entries()[1:]}
    )
    assert "sampled-selection" in grade_wow_run(tampered).hard_failures


def test_a_loud_disputed_member_is_not_sampling_and_the_run_passes() -> None:
    """An explicit, evidence-cited could-not-tell in a selected family is lawful.

    Observed failing on the unchanged tree: the honest focused ledger scored 67
    (coverage smeared over fourteen rows, zero autonomy points for FOCUSED).
    """

    grade = grade_wow_run(_honest_focused_ledger())
    assert "sampled-selection" not in grade.hard_failures
    assert grade.hard_failures == ()
    assert grade.passed is True


def test_focused_depth_is_scored_on_the_selected_families() -> None:
    """Pass-2 depth grades where the person pointed, not the whole manifest.

    Observed failing on the unchanged tree: three determinate rows over
    fourteen scored 5 of 25.
    """

    grade = grade_wow_run(_honest_focused_ledger())
    assert grade.significant_coverage == 25


def test_a_complete_focused_audit_earns_autonomy_points() -> None:
    """Observed failing on the unchanged tree: FOCUSED audits scored zero."""

    grade = grade_wow_run(_honest_focused_ledger())
    assert grade.autonomy_and_clarity == 5


def test_an_incomplete_focused_audit_is_a_hard_failure() -> None:
    """Observed absent on the unchanged tree: only GUIDED audits could fire it."""

    grade = grade_wow_run(_honest_focused_ledger(audit=_focused_audit(completed=7)))
    assert "incomplete-packets" in grade.hard_failures


def test_an_honest_focused_run_outscores_a_hollow_shape_perfect_one() -> None:
    """The fixture pair the scoring rebalance ships with.

    The register row's shame was a fabricated ledger outscoring an honest one
    95 to 84.  Its spirit re-run: the shape-perfect evidence-free focused
    ledger must hard-fail, and the honest one must outscore it.
    """

    honest = grade_wow_run(_honest_focused_ledger())
    hollow = grade_wow_run(_hollow_focused_ledger())

    assert honest.passed is True
    assert hollow.passed is False
    assert hollow.hard_failures != ()
    assert "sampled-selection" in hollow.hard_failures
    assert "unsupported-claim" in hollow.hard_failures
    assert honest.score > hollow.score


def test_the_register_reproduction_still_hard_fails() -> None:
    """RISK-WOW-GATE-SCORES-SHAPE's fabricated ledger can never pass again."""

    grade = grade_wow_run(_fabricated_ledger(), audit=autonomous_audit())
    assert grade.hard_failures != ()
    assert grade.passed is False
    assert grade.score < 90
