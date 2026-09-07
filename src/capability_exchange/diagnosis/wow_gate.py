"""Aggregate Wow Gate scoring and hard-failure evaluation for guided diagnoses.

The gate grades the two-pass product on two separate axes:

*Pass-1 completeness* — all fourteen expectation rows present, each either
determinate with evidence the ledger holds or a loud, priced placeholder
(an ``unknown`` whose reason sentence is rendered, or the full ``not-gated``
manifest carrying its one fixed sentence).  An unpriced unknown anywhere is
the ``unpriced-unknown`` hard failure: "could not tell" must be loud, priced,
and rare, never a bare token.

*Pass-2 depth* — the six scored dimensions.  On a focused run the coverage
dimension grades the families the person selected, because depth-where-you-
pointed is what pass 2 promises; completeness across all fourteen is already
the other axis.  A focused ledger whose selected families hold any silent
not-assessed member is the ``sampled-selection`` hard failure — the
gate-level mirror of the engine's close rule, kept as belt and braces
against tampered stores.

What this grader can and cannot prove, stated plainly because a score is
easily mistaken for more than it is:

It reads one closed ledger and its audit. It can check that the ledger is
*internally consistent* — that a claim cites evidence the ledger itself
records, that a determinate finding carries evidence, that repeated citation
of one identity is counted once. It cannot check that the evidence is
*authentic*, because a ledger declares its own evidence and the grader never
sees the fingerprint the tokens were minted from. A wholly fabricated but
internally consistent ledger can therefore still grade well here on the
dimensions its fabrications satisfy.

Authenticity is the engine's job, upstream, where the minted token set is
known: comparison re-derives its inputs and refuses stored artifacts that
disagree (see the closed RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT row in
docs/RISK-REGISTER.md). A passing grade on a ledger the engine never closed
is a claim about that ledger's arithmetic, not about any inspected system.
"""

from __future__ import annotations

from pydantic import Field

from capability_exchange.diagnosis.comparison import (
    ComparisonLedger,
    Disposition,
    InsightKind,
    ledger_evidence_identities,
)
from capability_exchange.diagnosis.expectations import (
    NOT_GATED_REASON,
    WOW_EXPECTATIONS,
    ExpectationState,
)
from capability_exchange.diagnosis.payload_guard import (
    HostilePayloadError,
    refuse_hostile_payload,
)
from capability_exchange.diagnosis.ranking import MAX_RECOMMENDATIONS
from capability_exchange.diagnosis.run import _ValidatedInventoried
from capability_exchange.diagnosis.work import AnalysisMode, WorkAudit
from capability_exchange.diagnosis.workflows import WorkflowGraph

__all__ = ["WowGrade", "grade_wow_run"]

#: Audit modes whose packets are engine-issued autonomous work.  FOCUSED is
#: the two-pass product's default; GUIDED remains the all-families sweep.
_AUTONOMOUS_MODES = frozenset({AnalysisMode.GUIDED, AnalysisMode.FOCUSED})

_SENTENCE_ENDINGS = (".", "!", "?")


class WowGrade(_ValidatedInventoried):
    significant_coverage: int = Field(ge=0, le=25)
    workflow_quality: int = Field(ge=0, le=20)
    recommendation_quality: int = Field(ge=0, le=20)
    reciprocal_quality: int = Field(ge=0, le=15)
    evidence_integrity: int = Field(ge=0, le=15)
    autonomy_and_clarity: int = Field(ge=0, le=5)
    #: Pass-1 completeness, graded separately from the 100-point depth score:
    #: how many of the fourteen manifest rows are either determinate with held
    #: evidence or a loud priced placeholder.  Anything below fourteen also
    #: carries the hard failure naming what broke.
    pass_one_completeness: int = Field(ge=0, le=14)
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
        return (
            self.score >= 90
            and self.pass_one_completeness == len(WOW_EXPECTATIONS)
            and not self.hard_failures
        )


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


def _is_priced(item: object) -> bool:
    """An unknown is priced when its reason sentence is actually rendered.

    The model type guarantees a non-empty reason, so the check here is the
    part the type cannot: the reason must read as a sentence a person was
    shown — more than one word, closed with terminal punctuation — not a
    bare state token restated.  The truth of the sentence is the engine's
    job upstream; the gate refuses the silent shape.
    """

    text = str(getattr(item, "reason", "") or "").strip()
    return len(text.split()) >= 2 and text.endswith(_SENTENCE_ENDINGS)


def _not_gated_is_lawful(item: object, *, whole_manifest_not_gated: bool) -> bool:
    """A not-gated row is lawful only inside the full loud placeholder manifest.

    ``assess_wow_expectations`` mints not-gated as all fourteen rows or none,
    each carrying exactly the one fixed sentence and no evidence.  A partial
    or reworded not-gated manifest is a shape the engine cannot produce, so
    the gate refuses it rather than trusting a tampered store.
    """

    return (
        whole_manifest_not_gated
        and getattr(item, "reason", None) == NOT_GATED_REASON
        and not tuple(getattr(item, "evidence_ids", ()) or ())
    )


def _gated_expectations(ledger: ComparisonLedger) -> tuple[object, ...]:
    """Expectation rows the family machinery actually gated.

    A ``not-gated`` row is a loud typed placeholder — the catalogue carries no
    signed family contract, so the row states why nothing could be gated. It
    is not a claim and carries no evidence by construction; counting it as a
    claim would turn the placeholder itself into an unsupported-claim hard
    failure, punishing exactly the loudness item 2 exists to force.
    """

    return tuple(
        item
        for item in ledger.expectations
        if getattr(item, "state", None) is not ExpectationState.NOT_GATED
    )


def _claim_expectations(ledger: ComparisonLedger) -> tuple[object, ...]:
    """Expectation rows that assert something and so must cite held evidence.

    Determinate rows always claim.  An ``unknown`` row claims only when it
    cites evidence — a fabricated citation on an Unknown stays an
    unsupported claim — while an evidence-free Unknown asserts nothing and is
    governed by the priced-loudness rule instead, so honesty is never scored
    as fabrication.
    """

    return tuple(
        item
        for item in ledger.expectations
        if getattr(item, "state", None) in _DETERMINATE_STATES
        or (
            getattr(item, "state", None) is ExpectationState.UNKNOWN
            and tuple(getattr(item, "evidence_ids", ()) or ())
        )
    )


def _all_claims(ledger: ComparisonLedger) -> tuple[object, ...]:
    return (
        *ledger.strengths,
        *ledger.reciprocal_lessons,
        *ledger.workflow_insights,
        *ledger.ranked_recommendations,
        *_claim_expectations(ledger),
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


def _manifest_in_order(ledger: ComparisonLedger) -> bool:
    return (
        tuple(getattr(item, "family_id", None) for item in ledger.expectations)
        == WOW_EXPECTATIONS
    )


def _significant_coverage(ledger: ComparisonLedger, held: frozenset[str]) -> int:
    """Score what was determined, not how many rows were emitted.

    ``UNKNOWN`` earns nothing: "we could not tell" is an honest answer but it
    is not coverage. A determinate state earns nothing either unless it cites
    evidence the ledger holds, because a verdict without evidence is a guess
    wearing a verdict's clothes.

    On a focused run the denominator is the selected families: pass-2 depth
    is graded where the person pointed, and completeness across all fourteen
    rows is the separate pass-1 axis.  A guided or inventory ledger keeps the
    original 25-point logic over the whole manifest, unchanged.
    """

    if not ledger.expectations or not _manifest_in_order(ledger):
        return 0
    selected = set(ledger.focus_selected_family_ids)
    scored = (
        tuple(item for item in ledger.expectations if item.family_id in selected)
        if selected
        else ledger.expectations
    )
    if not scored:
        return 0
    determined = sum(
        1
        for item in scored
        if getattr(item, "state", None) in _DETERMINATE_STATES and _is_supported(item, held)
    )
    return min(25, round(25 * determined / len(scored)))


def _pass_one_completeness(ledger: ComparisonLedger, held: frozenset[str]) -> int:
    """Count manifest rows that are either determinate-with-evidence or loud.

    The count is the pass-1 axis of the two-pass grade: fourteen rows, each
    determinate with held evidence, or an Unknown whose price sentence is
    rendered, or part of the full lawful not-gated manifest.  A row failing
    all three earns nothing here and also raises its own hard failure, so
    the sub-score never silently substitutes for the refusal.
    """

    if not _manifest_in_order(ledger):
        return 0
    whole_manifest_not_gated = all(
        getattr(item, "state", None) is ExpectationState.NOT_GATED
        for item in ledger.expectations
    )
    count = 0
    for item in ledger.expectations:
        state = getattr(item, "state", None)
        if state in _DETERMINATE_STATES and _is_supported(item, held):
            count += 1
        elif state is ExpectationState.NOT_GATED and _not_gated_is_lawful(
            item, whole_manifest_not_gated=whole_manifest_not_gated
        ):
            count += 1
        elif (
            state is ExpectationState.UNKNOWN
            and _is_priced(item)
            and (not item.evidence_ids or _is_supported(item, held))
        ):
            count += 1
    return count


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
    if audit.mode not in _AUTONOMOUS_MODES:
        return 0
    if audit.completed_count < audit.packet_count:
        return 1
    if audit.unresolved_count:
        return 2
    return 5


def _sampled_selection(ledger: ComparisonLedger, audit: WorkAudit | None) -> bool:
    """True when a focused ledger's selected families hold silent members.

    The engine already refuses to close such a run; this is the gate-level
    mirror, belt and braces against tampered stores.  A member is *silent*
    when its entry is ``not-assessed`` with no evidence references — exactly
    the seeded row no proposal ever cited.  A loud could-not-tell (a recorded
    dispute or withheld method verdict) carries its proposals' evidence and
    is lawful.  Missing selection facts on a focused ledger fail closed: a
    FOCUSED audit with no recorded selection, or a selected family with no
    ledger row, is a shape the engine cannot mint.
    """

    focused = bool(ledger.focus_selected_family_ids) or (
        audit is not None and audit.mode is AnalysisMode.FOCUSED
    )
    if not focused:
        return False
    selected = ledger.focus_selected_family_ids
    if not selected:
        return True
    families = {item.family_id: item for item in ledger.family_entries}
    entries = {item.catalogue_id: item for item in ledger.entries}
    for family_id in selected:
        family = families.get(family_id)
        if family is None:
            return True
        members = (*family.available_member_ids, *family.unavailable_member_ids)
        for member_id in members:
            entry = entries.get(member_id)
            if entry is None:
                return True
            if (
                entry.disposition is Disposition.NOT_ASSESSED
                and not entry.evidence_references
            ):
                return True
    return False


def _hard_failures(
    ledger: ComparisonLedger, audit: WorkAudit | None, held: frozenset[str]
) -> tuple[str, ...]:
    failures: list[str] = []
    # `manual-proposal` and `digest-drift` are deliberately absent. Both
    # restated invariants WorkAudit already enforces on itself, so neither
    # could ever fire; `_audit_for` asks the question the model cannot, which
    # is whether this audit belongs to this ledger.
    if audit is not None and audit.mode in _AUTONOMOUS_MODES:
        if audit.completed_count < audit.packet_count:
            failures.append("incomplete-packets")
    if ledger.expectations and not _manifest_in_order(ledger):
        failures.append("missing-expectation")
    elif not ledger.expectations:
        # An absent manifest is the first real run's silent hole.  Even a
        # family-free catalogue must yield fourteen loud not-gated rows, so a
        # ledger carrying no expectation rows at all is a hard failure.
        failures.append("missing-expectation")
    whole_manifest_not_gated = bool(ledger.expectations) and all(
        getattr(item, "state", None) is ExpectationState.NOT_GATED
        for item in ledger.expectations
    )
    if any(
        (
            getattr(item, "state", None) is ExpectationState.UNKNOWN
            and not _is_priced(item)
        )
        or (
            getattr(item, "state", None) is ExpectationState.NOT_GATED
            and not _not_gated_is_lawful(
                item, whole_manifest_not_gated=whole_manifest_not_gated
            )
        )
        for item in ledger.expectations
    ):
        failures.append("unpriced-unknown")
    if _sampled_selection(ledger, audit):
        failures.append("sampled-selection")
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
    # Not-gated placeholders do not switch on the rich-surprise demand: the
    # family machinery is absent for such a catalogue, exactly as when the
    # manifest used to be empty.
    rich_surprise_required = bool(ledger.workflow_graph.edges) and bool(
        _gated_expectations(ledger)
    )
    if rich_surprise_required and not ledger.workflow_insights:
        failures.append("missing-rich-surprise")
    return tuple(failures)


def _audit_for(ledger: ComparisonLedger, supplied: WorkAudit | None) -> WorkAudit | None:
    """The audit this ledger was closed with, refusing any other.

    A separate audit file is not evidence about this run: it can be another
    run's, or hand-written. The ledger carries its own audit inside the
    canonical payload and the digest, so that is what grades. A supplied audit
    is accepted only as a cross-check, and only when it agrees.

    This replaces two hard failures that could never fire. ``manual-proposal``
    and ``digest-drift`` both restated invariants ``WorkAudit`` already
    enforces on itself, so neither could catch anything. Whether the audit
    belongs to the ledger is the question the model cannot answer alone.
    """

    bound = ledger.work_audit
    if supplied is None:
        return bound
    if bound is None:
        raise ValueError("audit does not belong to this ledger: the ledger carries none")
    if supplied != bound:
        raise ValueError("audit does not belong to this ledger")
    return bound


def grade_wow_run(ledger: ComparisonLedger, audit: WorkAudit | None = None) -> WowGrade:
    """Score one closed diagnosis from typed ledger and audit fields only."""

    audit = _audit_for(ledger, audit)
    held = ledger_evidence_identities(ledger)
    hard_failures = _hard_failures(ledger, audit, held)
    return WowGrade(
        significant_coverage=_significant_coverage(ledger, held),
        workflow_quality=_workflow_quality(ledger.workflow_graph, held),
        recommendation_quality=_recommendation_quality(ledger, held),
        reciprocal_quality=_reciprocal_quality(ledger, held),
        evidence_integrity=_evidence_integrity(ledger, held),
        autonomy_and_clarity=_autonomy_and_clarity(audit),
        pass_one_completeness=_pass_one_completeness(ledger, held),
        hard_failures=hard_failures,
    )
