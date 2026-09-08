"""Ledger-derived diagnosis facts. Markdown cannot invent its own totals."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from contextvars import ContextVar
from pathlib import Path
from typing import Self

from pydantic import ConfigDict, Field, PrivateAttr, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.comparison import (
    ComparisonLedger,
    Disposition,
    GroundedInsight,
    ledger_evidence_identities,
)
from capability_exchange.diagnosis.finding import Finding
from capability_exchange.diagnosis.observations import (
    HealthState,
    ObservationKind,
    RuntimeState,
)
from capability_exchange.diagnosis.receipts import (
    DecisionState,
    RecommendationDecision,
    ShareReceipt,
    ShareState,
)
from capability_exchange.diagnosis.run import RunIdentity
from capability_exchange.diagnosis.significant_families import (
    FamilyAssessmentDisposition,
)

__all__ = [
    "LedgerSummary",
    "ReportModel",
    "canonical_coverage_block",
    "canonical_fact_block",
    "canonical_job_axis_block",
    "canonical_ledger_appendix",
    "canonical_ledger_digest",
    "canonical_ledger_payload",
    "canonical_release_gap_block",
    "coverage_block_errors",
    "job_axis_errors",
    "ledger_appendix_errors",
    "ledger_derived_fact_errors",
]

_FROM_LEDGER = ContextVar("_ledger_summary_from_ledger", default=False)
_FROM_RESULT = ContextVar("_report_model_from_result", default=False)
_COVERAGE_CLAIM = re.compile(
    r"\b(\d+)\s+"
    r"(?:"
    r"capabilities?\s+(?:are\s+)?(?:already\s+)?covered"
    r"|capabilities?\s+remain(?:s)?\s+unknown"
    r"|(?:catalogue\s+)?entries"
    r"|assessed"
    r"|remain(?:s)?\s+unknown"
    r")",
    re.IGNORECASE,
)


def _job_axis_row(item: object) -> dict[str, object]:
    return {
        "job_id": item.job_id,
        "label": item.label,
        "state": item.state.value,
        "evidence_references": list(item.evidence_references),
        "observation_ids": list(item.observation_ids),
        "reason": item.reason,
    }


def _insight_row(item: GroundedInsight) -> dict[str, object]:
    return {
        "insight_id": item.insight_id,
        "kind": item.kind.value,
        "title": item.title,
        "explanation": item.explanation,
        "evidence_ids": list(item.evidence_ids),
        "observation_ids": list(item.observation_ids),
        "workflow_ids": list(item.workflow_ids),
    }


def _home_relative_location(location: str) -> str | None:
    """Render a report location home-relative, or ``None`` when it cannot be.

    WO-022, decided 2026-09-03: the footer lives in the most shareable
    artifact Lens produces, and an absolute home path carries the person's
    username. A location under the home directory renders as ``~/…``. The
    storage path arrives resolved (``default_lens_app_storage`` resolves
    symlinks and honours ``XDG_STATE_HOME``) while ``Path.home()`` does
    neither, so both the written and the resolved location are tried against
    both the written and the resolved home. When nothing matches — for
    example ``XDG_STATE_HOME`` outside home — the caller renders no path at
    all: no footer may ever carry an absolute path.
    """

    written = Path(location)
    homes: list[Path] = []
    for home in (Path.home(), Path.home().resolve(strict=False)):
        if home not in homes:
            homes.append(home)
    candidates: list[Path] = [written]
    if written.is_absolute():
        resolved = written.resolve(strict=False)
        if resolved not in candidates:
            candidates.append(resolved)
    for candidate in candidates:
        for home in homes:
            try:
                return "~/" + candidate.relative_to(home).as_posix()
            except ValueError:
                continue
    return None


def canonical_ledger_payload(ledger: ComparisonLedger) -> dict[str, object]:
    """Return the one stable structured payload used by digest and storage."""

    return {
        "catalogue_sha256": ledger.catalogue_sha256,
        "catalogue_version": ledger.catalogue_version,
        "capabilities": [
            {
                "capability_id": item.capability_id,
                "catalogue_ids": list(item.catalogue_ids),
                "job_ids": list(item.job_ids),
                "person_observation_ids": list(item.person_observation_ids),
                "title": item.title,
            }
            for item in sorted(ledger.capabilities, key=lambda item: item.capability_id)
        ],
        "entries": [
            {
                "capability_id": item.capability_id,
                "catalogue_id": item.catalogue_id,
                "disposition": item.disposition.value,
                "evidence_references": sorted(item.evidence_references),
                "method_compared": item.method_compared,
                "reason": item.reason,
            }
            for item in sorted(ledger.entries, key=lambda item: item.catalogue_id)
        ],
        "ranked_recommendations": [
            {
                "catalogue_id": item.catalogue_id,
                "capability_id": item.capability_id,
                "factors": {
                    "reliability_risk": item.factors.reliability_risk,
                    "job_relevance": item.factors.job_relevance,
                    "workflow_leverage": item.factors.workflow_leverage,
                    "evidence_strength": item.factors.evidence_strength,
                    "adoption_effort": item.factors.adoption_effort,
                },
                "evidence_ids": list(item.evidence_ids),
                "observation_ids": list(item.observation_ids),
                "reason": item.reason,
                "rank": item.rank,
            }
            for item in ledger.ranked_recommendations
        ],
        "mcp_tools_by_server": [
            {
                "declared_tool_count": item.declared_tool_count,
                "inventory_status": item.inventory_status,
                "server_id": item.server_id,
                "server_name": item.server_name,
                "tools": list(item.tools),
            }
            for item in sorted(ledger.mcp_tools_by_server, key=lambda item: item.server_id)
        ],
        "family_entries": [
            _family_row(item)
            for item in sorted(ledger.family_entries, key=lambda item: item.family_id)
        ],
        "version_distance": (
            {
                "current_version": ledger.version_distance.current_version,
                "evidence_references": list(ledger.version_distance.evidence_references),
                "families": [
                    _family_delta_row(item)
                    for item in sorted(
                        ledger.version_distance.families,
                        key=lambda item: item.family_id,
                    )
                ],
                "inspected_version": ledger.version_distance.inspected_version,
                "newer_release_ids": list(ledger.version_distance.newer_release_ids),
            }
            if ledger.version_distance is not None
            else None
        ),
        "local_entries": [
            {
                "disposition": item.disposition.value,
                "evidence_references": list(item.evidence_references),
                "identity": item.identity,
                "kind": item.kind.value,
                "limitation": item.limitation,
                "mapped_capability_ids": list(item.mapped_capability_ids),
                "mapped_catalogue_ids": list(item.mapped_catalogue_ids),
                "observation_id": item.observation_id,
                "configuration_state": item.configuration_state.value,
                "runtime_state": item.runtime_state.value,
                "health_state": item.health_state.value,
                "reason": item.reason,
            }
            for item in sorted(ledger.local_entries, key=lambda item: item.observation_id)
        ],
        "reciprocal_answer": ledger.reciprocal_answer,
        "workflow_graph": {
            "nodes": [
                {
                    "node_id": item.node_id,
                    "kind": item.kind.value,
                    "configuration_state": item.configuration_state.value,
                    "runtime_state": item.runtime_state.value,
                    "health_state": item.health_state.value,
                    "evidence_ids": list(item.evidence_ids),
                }
                for item in sorted(ledger.workflow_graph.nodes, key=lambda item: item.node_id)
            ],
            "edges": [
                {
                    "workflow_id": item.workflow_id,
                    "source_id": item.source_id,
                    "target_id": item.target_id,
                    "kind": item.kind.value,
                    "evidence_ids": list(item.evidence_ids),
                }
                for item in sorted(
                    ledger.workflow_graph.edges,
                    key=lambda item: (
                        item.workflow_id,
                        item.source_id,
                        item.target_id,
                        item.kind.value,
                    ),
                )
            ],
        },
        "work_audit": (
            ledger.work_audit.model_dump(mode="json") if ledger.work_audit is not None else None
        ),
        "expectations": [
            {
                "family_id": item.family_id,
                "state": item.state.value,
                "evidence_ids": list(item.evidence_ids),
                "reason": item.reason,
            }
            for item in ledger.expectations
        ],
        "strengths": [_insight_row(item) for item in ledger.strengths],
        "reciprocal_lessons": [_insight_row(item) for item in ledger.reciprocal_lessons],
        "workflow_insights": [_insight_row(item) for item in ledger.workflow_insights],
        "unique_to_you": list(ledger.unique_to_you),
        # Present only when a focused run recorded a selection, so every
        # guided/inventory ledger — including every one saved before the mode
        # existed — keeps its exact digest, while a focused ledger's digest
        # binds the selection facts the decisions section renders.
        **(
            {
                "focus_selected_family_ids": list(ledger.focus_selected_family_ids),
                "focus_unselected_family_ids": list(ledger.focus_unselected_family_ids),
            }
            if ledger.focus_selected_family_ids or ledger.focus_unselected_family_ids
            else {}
        ),
        # Present only on a non-lineage run, so every lineage ledger —
        # including every one saved before the job axis existed — keeps its
        # exact digest, while a non-lineage ledger's digest binds its job rows.
        **(
            {"job_axis": [_job_axis_row(item) for item in ledger.job_axis]}
            if ledger.job_axis
            else {}
        ),
    }


def canonical_ledger_digest(ledger: ComparisonLedger) -> str:
    """Return a stable SHA-256 binding for one exact comparison ledger."""

    encoded = json.dumps(
        canonical_ledger_payload(ledger),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class LedgerSummary(InventoriedModel):
    """Closed coverage counts derived from one comparison ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(ge=1)
    by_disposition: dict[Disposition, int]
    assessed: int = Field(ge=0)
    unknown: int = Field(ge=0)

    def __init__(self, *args: object, **kwargs: object) -> None:
        if not _FROM_LEDGER.get():
            raise TypeError("LedgerSummary can only be created with from_ledger()")
        super().__init__(*args, **kwargs)

    @classmethod
    def from_ledger(cls, ledger: ComparisonLedger) -> Self:
        counts = Counter(item.disposition for item in ledger.entries)
        unknown = counts[Disposition.NOT_ASSESSED]
        token = _FROM_LEDGER.set(True)
        try:
            return cls(
                total=len(ledger.entries),
                by_disposition={item: counts[item] for item in Disposition},
                assessed=len(ledger.entries) - unknown,
                unknown=unknown,
            )
        finally:
            _FROM_LEDGER.reset(token)

    @model_validator(mode="after")
    def _counts_are_internally_consistent(self) -> Self:
        if set(self.by_disposition) != set(Disposition):
            raise ValueError("ledger summary must count every closed disposition")
        if sum(self.by_disposition.values()) != self.total:
            raise ValueError("ledger summary disposition counts must equal the total")
        if self.by_disposition[Disposition.NOT_ASSESSED] != self.unknown:
            raise ValueError("ledger summary unknown count must match not-assessed")
        if self.assessed + self.unknown != self.total:
            raise ValueError("ledger summary assessed and unknown must equal the total")
        return self

    def canonical_markdown(self) -> str:
        dispositions = ", ".join(
            f"{item.value}={self.by_disposition[item]}" for item in Disposition
        )
        return (
            f"- Catalogue accounting: {self.total} entries; "
            f"{self.assessed} assessed; {self.unknown} remain Unknown.\n"
            f"- Dispositions: {dispositions}.\n"
        )

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if update and any(
            field in update for field in ("total", "by_disposition", "assessed", "unknown")
        ):
            raise TypeError("LedgerSummary can only be created with from_ledger()")
        token = _FROM_LEDGER.set(True)
        try:
            values = {
                field_name: getattr(self, field_name) for field_name in type(self).model_fields
            }
            if update:
                values.update(update)
            return type(self).model_validate(values)
        finally:
            _FROM_LEDGER.reset(token)

    def copy(self, **kwargs: object) -> Self:
        raise TypeError("copy() is disabled for LedgerSummary; use from_ledger()")

    @classmethod
    def model_construct(
        cls,
        _fields_set: set[str] | None = None,
        **values: object,
    ) -> Self:
        if not _FROM_LEDGER.get():
            raise TypeError("LedgerSummary can only be created with from_ledger()")
        return cls.model_validate(values)


class ReportModel(InventoriedModel):
    """Typed report bound to one run identity and one exact ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_identity: RunIdentity
    ledger_summary: LedgerSummary
    ledger_sha256: str = Field(pattern=r"^(?:sha256:)?[0-9a-f]{64}$")
    strongest_findings: tuple[Finding, ...] = ()
    reciprocal_findings: tuple[Finding, ...] = ()
    reliability_findings: tuple[Finding, ...] = ()
    limits: tuple[str, ...] = ()
    decisions: tuple[RecommendationDecision, ...] = ()
    share_state: ShareState = ShareState.NOT_OFFERED
    share_receipt: ShareReceipt | None = None
    _report_location: str | None = PrivateAttr(default=None)

    def __init__(self, *args: object, **kwargs: object) -> None:
        if not _FROM_RESULT.get():
            raise TypeError("ReportModel can only be created with from_result()")
        super().__init__(*args, **kwargs)

    @classmethod
    def from_result(
        cls,
        *,
        run_identity: RunIdentity,
        ledger: ComparisonLedger,
        ledger_sha256: str,
        findings: tuple[Finding, ...] = (),
        limits: tuple[str, ...] = (),
        decisions: tuple[RecommendationDecision, ...] = (),
        share_state: ShareState = ShareState.NOT_OFFERED,
        share_receipt: ShareReceipt | None = None,
        report_location: str | None = None,
    ) -> Self:
        expected = canonical_ledger_digest(ledger)
        supplied = (
            ledger_sha256 if ledger_sha256.startswith("sha256:") else f"sha256:{ledger_sha256}"
        )
        if supplied != expected:
            raise ValueError("report must bind the exact comparison ledger")
        _validate_ledger_insights(ledger)
        token = _FROM_RESULT.set(True)
        try:
            report = cls(
                run_identity=run_identity,
                ledger_summary=LedgerSummary.from_ledger(ledger),
                ledger_sha256=expected,
                strongest_findings=findings,
                reciprocal_findings=(),
                reliability_findings=(),
                limits=limits,
                decisions=decisions,
                share_state=share_state,
                share_receipt=share_receipt,
            )
            report._report_location = report_location
            return report
        finally:
            _FROM_RESULT.reset(token)

    @model_validator(mode="after")
    def _share_and_decisions_are_receipt_backed(self) -> Self:
        if self.share_receipt is None:
            if self.share_state is ShareState.SENT:
                raise ValueError("sent share state requires a share receipt")
            if self.share_state is ShareState.PREVIEWED:
                raise ValueError("previewed share state requires a share receipt")
        else:
            if self.share_receipt.run_id != self.run_identity.run_id:
                raise ValueError("share receipt run_id must match the report run")
            if self.share_state is not self.share_receipt.state:
                raise ValueError("share_state must match the share receipt")
            if self.share_state is ShareState.SENT and not self.share_receipt.was_sent:
                raise ValueError("sent share state requires a sent share receipt")
        for decision in self.decisions:
            receipt = decision.receipt
            if receipt is not None and receipt.run_id != self.run_identity.run_id:
                raise ValueError("decision receipt run_id must match the report run")
        return self

    def render_markdown(self, ledger: ComparisonLedger) -> str:
        block = canonical_fact_block(ledger)
        appendix = canonical_ledger_appendix(ledger)
        limits = "\n".join(f"- {item}" for item in self.limits)
        extra = f"{limits}\n" if limits else ""
        return (
            "# Diagnosis\n\n"
            f"{_render_what_was_read(ledger)}"
            f"\n{_render_what_you_told_me(ledger)}"
            f"\n{canonical_coverage_block(ledger)}"
            f"\n{canonical_release_gap_block(ledger)}"
            f"\n{_render_job_axis(ledger)}"
            f"\n{_render_version_distance(ledger)}"
            f"\n{_render_grounded_strengths(ledger)}"
            f"\n{_render_strengths(ledger)}"
            f"\n{_render_reciprocal_learning(ledger)}"
            f"\n{_render_unique_to_you(ledger)}"
            f"\n{_render_ranked_recommendations(ledger)}"
            f"\n{_render_recommendations(ledger)}"
            f"\n{_render_workflow_connections(ledger)}"
            f"\n{_render_rejections(ledger)}"
            f"\n{_render_fragility(ledger)}"
            "\n## Coverage and limits\n"
            f"{block}"
            f"{extra}"
            f"\n{_render_family_coverage(ledger)}"
            f"\n{_render_wow_expectations(ledger)}"
            f"\n{appendix}"
            "\n"
            f"{self._render_decisions(ledger)}"
            "\n"
            f"{self._render_close(ledger)}"
        )

    def _render_decisions(self, ledger: ComparisonLedger) -> str:
        lines = ["## What you decided"]
        # A focused run's family multi-select is itself a decision the next
        # run must remember: what was examined by choice, and what was
        # explicitly left for later.  The facts come from the ledger, which
        # copied them from the engine-validated focus receipt.
        if ledger.focus_selected_family_ids:
            lines.append(
                "- Focused this run on: "
                + ", ".join(ledger.focus_selected_family_ids)
            )
        if ledger.focus_unselected_family_ids:
            lines.append(
                "- Explicitly not selected this run: "
                + ", ".join(ledger.focus_unselected_family_ids)
            )
        # The share-back offer's fate joins the same decisions record (design
        # item 10), derived only from the typed share state and its receipt:
        # a shared idea is never offered again, and the next run reads this
        # section before offering anything. Declined and deferred answers are
        # given after this report is rendered, so they are recorded by the
        # host flow in its own "Share-back idea" lines, never invented here.
        if self.share_state is ShareState.SENT:
            lines.append(
                "- Share-back offer — shared; a shared idea is never offered again."
            )
        elif self.share_state is ShareState.PREVIEWED:
            lines.append("- Share-back offer — previewed; nothing was sent.")
        elif self.share_state is ShareState.OFFERED:
            lines.append("- Share-back offer — offered; nothing was sent.")
        for decision in self.decisions:
            fate = "offered" if decision.state is DecisionState.OFFERED else "taken"
            lines.append(f"- {decision.catalogue_id} — {fate}")
        if len(lines) == 1:
            lines.append("No decisions were on the table this time.")
        return "\n".join(lines) + "\n"

    def _render_share_choice(self) -> str:
        receipt = self.share_receipt
        if (
            receipt is not None
            and receipt.was_sent
            and receipt.destination_class is not None
            and receipt.response_receipt_digest is not None
        ):
            destination = receipt.destination_class.value
            return (
                f"This disclosure was shared to {destination} "
                f"with digest {receipt.disclosure_sha256} "
                f"and response {receipt.response_receipt_digest}."
            )
        if self.share_state is ShareState.PREVIEWED:
            return "A contribution preview was shown. Nothing was sent."
        if self.share_state is ShareState.OFFERED:
            return "Sharing was offered. Nothing was sent."
        return "Sharing was not offered."

    def _render_close(self, ledger: ComparisonLedger) -> str:
        matched_observation_ids = {
            observation_id
            for family in ledger.family_entries
            for observation_id in family.matched_observation_ids
        }
        working_count = sum(
            item.observation_id in matched_observation_ids
            and (
                item.runtime_state is RuntimeState.OUTCOME_VERIFIED
                or item.health_state is HealthState.HEALTHY
            )
            for item in ledger.local_entries
        )
        if self.strongest_findings:
            strongest = self.strongest_findings[0].practical_implication
        elif working_count:
            strongest = (
                f"{working_count} matched {_plural(working_count, 'building block')} "
                f"{_plural(working_count, 'has', 'have')} verified outcome or health "
                "evidence."
            )
        elif matched_observation_ids:
            count = len(matched_observation_ids)
            strongest = (
                f"{count} configured {_plural(count, 'building block')} matched Dex's "
                "published families, but no working outcome was proven."
            )
        else:
            strongest = "No grounded strength cleared the evidence bar."
        learn_entries = sum(
            item.disposition is Disposition.DEX_SHOULD_LEARN for item in ledger.entries
        )
        if self.reciprocal_findings:
            learn = self.reciprocal_findings[0].practical_implication
        elif learn_entries:
            learn = (
                f"See {learn_entries} evidence-reviewed "
                f"{_plural(learn_entries, 'pattern')} above."
            )
        else:
            learn = "No transferable method cleared the evidence bar."
        recommendations = tuple(
            sorted(
                (
                    item
                    for item in ledger.entries
                    if item.disposition is Disposition.WORTH_BORROWING
                ),
                key=lambda item: item.catalogue_id,
            )
        )
        if len(recommendations) == 1:
            first_move = f"Consider `{recommendations[0].catalogue_id}`."
        elif recommendations:
            support_by_capability = {
                item.capability_id: len(item.person_observation_ids)
                for item in ledger.capabilities
            }
            scored = tuple(
                (
                    (
                        support_by_capability.get(item.capability_id, 0),
                        len(item.evidence_references),
                    ),
                    item.catalogue_id,
                )
                for item in recommendations
            )
            best_score = max(score for score, _catalogue_id in scored)
            best_supported = tuple(
                catalogue_id for score, catalogue_id in scored if score == best_score
            )
            if len(best_supported) == 1:
                first_move = (
                    f"Consider `{best_supported[0]}` (the best-supported option)."
                )
            else:
                first_move = (
                    "No single first move has stronger evidence than the other options above."
                )
        elif self.strongest_findings:
            first_move = self.strongest_findings[0].recommended_next_move
        else:
            first_move = "No first move cleared the bar."
        if self._report_location is None:
            report_location = "This report will be saved before the run closes."
        else:
            relative = _home_relative_location(self._report_location)
            report_location = (
                f"`{relative}`."
                if relative is not None
                else "saved in Lens's app storage — `dex-lens reports` lists it."
            )
        return (
            "## What happens next\n"
            f"- Already doing: {strongest}\n"
            f"- Dex should learn: {learn}\n"
            f"- First move: {first_move}\n"
            f"- Report location: {report_location}\n"
            f"- Return to this run: {self.run_identity.run_id}\n"
            f"- Sharing: {self._render_share_choice()}\n"
            "- Future watch: Future-watch is a separate choice from sharing. "
            "It was not started by this report.\n"
        )

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if update and any(
            field in update for field in ("ledger_summary", "ledger_sha256", "run_identity")
        ):
            raise TypeError("ReportModel can only be created with from_result()")
        token = _FROM_RESULT.set(True)
        try:
            values = {
                field_name: getattr(self, field_name) for field_name in type(self).model_fields
            }
            if update:
                values.update(update)
            return type(self).model_validate(values)
        finally:
            _FROM_RESULT.reset(token)

    def with_report_location(self, path: Path) -> Self:
        """Return a local display copy naming its exact app-storage destination."""

        location = str(path)
        if not location.strip() or "`" in location or "\n" in location or "\r" in location:
            raise ValueError("report location must be a non-empty single-line safe path")
        report = self.model_copy()
        report._report_location = location
        return report

    def copy(self, **kwargs: object) -> Self:
        raise TypeError("copy() is disabled for ReportModel; use from_result()")

    @classmethod
    def model_construct(
        cls,
        _fields_set: set[str] | None = None,
        **values: object,
    ) -> Self:
        if not _FROM_RESULT.get():
            raise TypeError("ReportModel can only be created with from_result()")
        return cls.model_validate(values)


#: How many unexamined catalogue identities the coverage block names outright
#: before counting the remainder. Enough to orient the reader; the complete
#: accounting is always one appendix away.
_COVERAGE_NAMED_BOUND = 8


def _named_with_remainder(identities: tuple[str, ...]) -> str:
    """The first few identities verbatim, and the rest counted, never hidden."""

    named = ", ".join(f"`{item}`" for item in identities[:_COVERAGE_NAMED_BOUND])
    remainder = len(identities) - min(len(identities), _COVERAGE_NAMED_BOUND)
    if remainder:
        return f"{named} and {remainder} more in the full record appendix"
    return named


#: Small counts spelled out, the way the block speaks them ("All fourteen
#: signed capability areas"). Anything larger stays a numeral; both render
#: deterministically.
_COUNT_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
)


def _count_words(count: int) -> str:
    return _COUNT_WORDS[count] if 0 <= count < len(_COUNT_WORDS) else str(count)


def _joined_titles(titles: tuple[str, ...]) -> str:
    if len(titles) == 1:
        return titles[0]
    return ", ".join(titles[:-1]) + " and " + titles[-1]


def _map_coverage_lines(
    ledger: ComparisonLedger, summary: LedgerSummary
) -> tuple[str, ...] | None:
    """The coverage-first voice, or ``None`` when this ledger cannot carry it.

    The voice is honest only when the ledger carries real map coverage: every
    signed family row actually assessed by the deterministic matcher, and —
    when a focused selection is recorded — every selected family named by the
    map with every one of its members individually examined. A focused ledger
    that violates its own coverage gate falls back to the confession rather
    than borrowing the triumphant voice.

    A ``not-assessed`` family row is minted at exactly one place: a family
    whose signed assessment is manual-only, where the catalogue itself says a
    person must review it. That is a priced, named fact, not a coverage gap —
    so it no longer flips the whole story into the confession (which told a
    person whose every area was assessed that nothing could be said about
    presence or absence, RISK-FIRST-READ-REPORT-VOICE-2026-09-08). The story
    counts such families out of "assessed" and names each with its signed
    reason.
    """

    if not ledger.family_entries:
        return None
    families_by_id = {family.family_id: family for family in ledger.family_entries}
    selected = ledger.focus_selected_family_ids
    if not set(selected) <= set(families_by_id):
        return None
    not_assessed = {
        entry.catalogue_id
        for entry in ledger.entries
        if entry.disposition is Disposition.NOT_ASSESSED
    }
    for family_id in selected:
        family = families_by_id[family_id]
        members = {*family.available_member_ids, *family.unavailable_member_ids}
        if members & not_assessed:
            return None
    area_count = len(ledger.family_entries)
    manual_rows = tuple(
        family
        for family in ledger.family_entries
        if family.disposition is FamilyAssessmentDisposition.NOT_ASSESSED
    )
    assessed_count = area_count - len(manual_rows)
    if manual_rows:
        lines = [
            f"{_count_words(assessed_count).capitalize()} of the "
            f"{_count_words(area_count)} signed capability "
            f"{_plural(area_count, 'area')} of Dex "
            f"{_plural(assessed_count, 'was', 'were')} assessed against "
            "your system."
        ]
        lines.extend(
            f"{family.title} (`{family.family_id}`) is one the signed "
            f"catalogue reserves for a person's own review: {family.reason}"
            for family in manual_rows
        )
    else:
        lines = [
            f"All {_count_words(area_count)} signed capability "
            f"{_plural(area_count, 'area')} of Dex "
            f"{_plural(area_count, 'was', 'were')} assessed against your system."
        ]
    if selected:
        titles = _joined_titles(
            tuple(
                f"{families_by_id[family_id].title} (`{family_id}`)"
                for family_id in selected
            )
        )
        inside = "it" if len(selected) == 1 else "them"
        lines.append(
            f"You took deep dives into {titles}; every capability inside "
            f"{inside} was examined individually, one by one."
        )
    if summary.unknown == 0:
        lines.append(
            f"Every one of the {summary.total} "
            f"{_plural(summary.total, 'entry', 'entries')} in the signed Dex "
            "catalogue was examined individually."
        )
    elif selected:
        other = area_count - len(selected)
        if other == 1:
            lines.append(
                "The other area is covered at the map level — a deeper look "
                "at it is one ask away."
            )
        elif other:
            lines.append(
                f"The other {_count_words(other)} areas are covered at the "
                "map level — a deeper look at any of them is one ask away."
            )
    else:
        lines.append(
            "Every area is covered at the map level — a deeper look at any "
            "of them is one ask away."
        )
    return tuple(lines)



#: Plain sentences for each recorded intake answer.  Closed maps, so the
#: report can only ever say what the option means -- never improvise.
_INTAKE_SENTENCES: dict[str, dict[str, str]] = {
    "dex-installed": {
        "yes": "You told me you have Dex installed.",
        "no": "You told me you don't have Dex installed.",
        "not-sure": "You told me you're not sure whether Dex is installed.",
    },
    "customisation": {
        "barely-touched": "You've barely changed the setup since installing it.",
        "quite-a-bit": "You've customised it quite a bit.",
        "unrecognisable": (
            "You've changed it so much it's unrecognisable from a fresh install."
        ),
        "not-sure": "You're not sure how much it has been customised.",
    },
    "first-installed": {
        "last-week": "You first installed it within the last week.",
        "last-month": "You first installed it within the last month.",
        "last-3-months": "You first installed it within the last three months.",
        "at-launch": "You first installed it when Dex first came out.",
        "not-sure": "You're not sure when you first installed it.",
    },
    "last-update": {
        "last-week": "You last updated it within the last week.",
        "last-month": "You last updated it within the last month.",
        "longer-ago": "You last updated it more than a month ago.",
        "never": "You've never updated it.",
        "not-sure": "You're not sure when it was last updated.",
    },
    "from-open-source": {
        "yes": "Your own system is built from an open-source project.",
        "no-built-it-myself": "You built your system yourself.",
        "not-sure": "You're not sure where your system originally came from.",
    },
}


def _render_what_you_told_me(ledger: ComparisonLedger) -> str:
    """The person's own answers, framed as theirs -- and any disagreement.

    Every sentence here rests on what the person said, so it says so; the
    measured claims elsewhere still come only from the signed record and the
    approved snapshot.  When an answer and the files disagree, both facts are
    stated side by side and neither silently wins: the disagreement is itself
    a finding worth their attention.
    """

    if not ledger.intake_answers:
        return ""
    answers = dict(item.partition("=")[::2] for item in ledger.intake_answers)
    lines = ["## What you told me"]
    for question_id in (
        "dex-installed",
        "customisation",
        "first-installed",
        "last-update",
        "from-open-source",
    ):
        answer = answers.get(question_id)
        if answer is None:
            continue
        sentence = _INTAKE_SENTENCES.get(question_id, {}).get(answer)
        if sentence is not None:
            lines.append(f"- {sentence}")
    link = answers.get("project-link")
    if link and link != "not-sure":
        lines.append(f"- The project it comes from: {link}")
    said_dex = answers.get("dex-installed")
    release_record_present = any(
        item.kind is ObservationKind.RELEASE and item.identity == "dex-core"
        for item in ledger.local_entries
    )
    if said_dex == "no" and release_record_present:
        lines.append(
            "- One thing doesn't line up: you told me you don't have Dex, but "
            "the approved folder carries Dex's own release record. If this "
            "setup was inherited or installed for you, that would explain it "
            "-- worth a look."
        )
    if said_dex == "yes" and not release_record_present:
        lines.append(
            "- One thing doesn't line up: you told me you have Dex, but I "
            "couldn't find Dex's release record in the approved folder. It "
            "may live in a folder you didn't approve, or on another machine."
        )
    lines.append(
        "These answers came from you, not from reading your files. They shape "
        "how this report speaks; every measured claim still comes from the "
        "signed record and the approved files alone."
    )
    return "\n".join(lines) + "\n"


def canonical_coverage_block(ledger: ComparisonLedger) -> str:
    """Headline coverage: lead with what was covered; confess only real holes.

    The first real run assessed 21 of 115 entries and the 94 left
    ``not-assessed`` hid in the appendix, so the first fix made this block a
    loud confession. The founder then rejected the failure-count voice for the
    two-pass product (2026-09-07): when the ledger carries real map coverage —
    every signed family row assessed, and any focused selection's members each
    individually examined — the block leads with what WAS covered: all areas
    assessed, the deep dives named, everything else covered at the map level
    and one ask away. The original confession stands verbatim as the fallback
    for a ledger lacking that map coverage, and the words "not examined"
    appear only there. Either way the block names signed catalogue and family
    identities only — never a label or path from the inspected system — and
    equivalent ledgers render it byte-identically.
    """

    summary = LedgerSummary.from_ledger(ledger)
    lines = ["## How much was examined"]
    story = _map_coverage_lines(ledger, summary)
    if story is not None:
        lines.extend(story)
        return "\n".join(lines) + "\n"
    if summary.unknown == 0:
        lines.append(
            f"All {summary.total} {_plural(summary.total, 'entry', 'entries')} in the "
            f"signed Dex catalogue {_plural(summary.total, 'was', 'were')} assessed "
            "against your system in this run."
        )
        return "\n".join(lines) + "\n"
    lines.append(
        f"Of the {summary.total} {_plural(summary.total, 'entry', 'entries')} in the "
        f"signed Dex catalogue, {summary.assessed} "
        f"{_plural(summary.assessed, 'was', 'were')} assessed against your system and "
        f"{summary.unknown} {_plural(summary.unknown, 'was', 'were')} not examined "
        "at all. Not examined means exactly that: nothing here says those "
        "capabilities are present or absent."
    )
    not_assessed = tuple(
        sorted(
            entry.catalogue_id
            for entry in ledger.entries
            if entry.disposition is Disposition.NOT_ASSESSED
        )
    )
    if ledger.family_entries:
        in_named_areas: set[str] = set()
        rows: list[tuple[int, str, str, int, int]] = []
        for family in ledger.family_entries:
            members = {*family.available_member_ids, *family.unavailable_member_ids}
            unexamined = members.intersection(not_assessed)
            if not unexamined:
                continue
            in_named_areas.update(unexamined)
            rows.append(
                (-len(unexamined), family.family_id, family.title, len(unexamined), len(members))
            )
        rows.sort()
        if rows:
            lines.append("The entries not examined sit in these signed capability areas:")
            for _negated, family_id, title, unexamined_count, member_count in rows:
                lines.append(
                    f"- {title} (`{family_id}`): {unexamined_count} of its {member_count} "
                    f"signed {_plural(member_count, 'member')} "
                    f"{_plural(unexamined_count, 'was', 'were')} not examined."
                )
        outside = tuple(item for item in not_assessed if item not in in_named_areas)
        if outside:
            lines.append(
                "- Outside every signed capability area: "
                f"{_named_with_remainder(outside)}."
            )
    else:
        lines.append(
            "No signed capability-family contract was present in this catalogue, so "
            "the entries not examined are named directly: "
            f"{_named_with_remainder(not_assessed)}."
        )
    lines.append(
        "A deeper look at these areas is a second, shorter run — it examines only "
        "what you point at."
    )
    return "\n".join(lines) + "\n"


def coverage_block_errors(report_markdown: str, ledger: ComparisonLedger) -> tuple[str, ...]:
    """Refuse a report shipped without its coverage story, whichever branch applies.

    The rule is byte-exact on purpose, like :func:`ledger_derived_fact_errors`:
    the block is rendered from the ledger alone, so the only report that lacks
    it is one that was edited after rendering or written around the engine —
    both of which are how 94 unexamined entries hid in an appendix once. Two
    branches owe the block: a ledger with unexamined entries owes the
    confession, and a ledger carrying map coverage owes the coverage-first
    story even when every entry was assessed. Only a fully assessed ledger
    with no map coverage owes nothing here.
    """

    summary = LedgerSummary.from_ledger(ledger)
    map_story = _map_coverage_lines(ledger, summary) is not None
    if summary.unknown == 0 and not map_story:
        return ()
    if canonical_coverage_block(ledger) in report_markdown:
        return ()
    if map_story:
        return (
            "say near the top how much was examined: this ledger carries the "
            "signed family-map coverage story — every signed capability area "
            "assessed, with any deep dives named — and the report does not "
            "carry the exact '## How much was examined' block telling it. "
            "Render the report from the diagnosis engine rather than editing "
            "it.",
        )
    return (
        f"say near the top how much was examined: this ledger left {summary.unknown} "
        f"of its {summary.total} signed catalogue entries not assessed, and the "
        "report does not carry the exact '## How much was examined' block naming "
        "where they sit. Render the report from the diagnosis engine rather than "
        "editing it.",
    )


#: Delta-shaped phrasings a non-lineage report may never carry: with zero
#: signed-identity matches there is no version to diff, so "behind Dex" has
#: nothing to cite.  The patterns are deliberately narrow — the engine's own
#: honest release-gap wording ("stands behind the current Dex release is
#: Unknown", "is behind or current") must never trip them.
_NON_LINEAGE_DELTA_CLAIM = re.compile(
    r"\bbehind\s+dex\b|\breleases?\s+behind\b|\bnew\s+since\s+your\b",
    re.IGNORECASE,
)

_JOB_STATE_PHRASES: dict[str, str] = {
    "serves": "you do this (specialist-reviewed; evidence cited)",
    "partially-serves": "you do part of this (specialist-reviewed; evidence cited)",
    "does-not-serve": (
        "nothing found doing this (specialist-reviewed; the cited evidence is "
        "the search itself)"
    ),
    "supported": (
        "something of the right shape exists (Supported: kind-level evidence "
        "only, not method verification)"
    ),
    "unknown": "could not tell (loud, priced)",
}


def canonical_job_axis_block(ledger: ComparisonLedger) -> str:
    """The non-lineage headline: the signed job axis, framed as a loan.

    Persona C — a person who never installed Dex — used to get a wall of
    UNRESOLVED family rows that read as "your system is invisible to us".
    When the engine classifies a run non-lineage (zero signed-identity
    matches; ``ledger.job_axis`` is the marker), this block renders one row
    per signed job: a validated pass-2 verdict with its evidence, the
    deterministic Supported from kind-admitted observations, or a loud priced
    Unknown.  The framing is engine-enforced as a loan, never a delta —
    "here is what Dex offers for this job", with no "behind" to cite.  Like
    :func:`canonical_coverage_block` it renders from the ledger alone, speaks
    signed job identities and closed states only, and equivalent ledgers
    render it byte-identically.  Empty on every lineage run.
    """

    if not ledger.job_axis:
        return ""
    lines = ["## What your system does about Dex's jobs"]
    lines.append(
        "You don't have Dex installed, so nothing here says you are behind "
        "or out of date — there is no version to compare (Verified: Dex's own "
        "release file, which every install carries, is not in the approved "
        "folder). Instead, the comparison is by the work itself: the jobs Dex "
        "is built around, and what your own system already does for each — "
        "read from your own files. Where Dex has something for a job, it is "
        "listed as something you could take, not something you are missing."
    )
    for row in ledger.job_axis:
        pointer = (
            f" {_render_human_evidence(row.evidence_references)}"
            if row.evidence_references
            else ""
        )
        lines.append(
            f"- {row.label} (`{row.job_id}`) — "
            f"{_JOB_STATE_PHRASES[row.state.value]}: {row.reason}{pointer}"
        )
    return "\n".join(lines) + "\n"


def job_axis_errors(report_markdown: str, ledger: ComparisonLedger) -> tuple[str, ...]:
    """Refuse a non-lineage report that drops the job axis or claims a delta.

    Applies only to a ledger carrying a job axis (the engine's non-lineage
    marker); every lineage ledger owes nothing here.  Two byte-exact rules,
    in the coverage-block mould: the exact engine-rendered job-axis block
    must be present, and no delta-framed claim ("behind Dex", "N releases
    behind", "new since your …") may appear anywhere — with zero identity
    matches such a claim has nothing to cite, so a report making it was
    edited after rendering or written around the engine.
    """

    if not ledger.job_axis:
        return ()
    errors: list[str] = []
    if canonical_job_axis_block(ledger) not in report_markdown:
        errors.append(
            "render the signed job axis: this ledger is non-lineage (no "
            "signed Dex identity matched), and the report does not carry the "
            "exact '## What your system does about Dex's jobs' block with one "
            "row per signed job. Render the report from the diagnosis engine "
            "rather than editing it."
        )
    claims = sorted(
        {match.group(0) for match in _NON_LINEAGE_DELTA_CLAIM.finditer(report_markdown)}
    )
    if claims:
        quoted = ", ".join(f"'{claim}'" for claim in claims)
        errors.append(
            "drop the release-delta framing: nothing ties this system to Dex, "
            f"so a claim like {quoted} has nothing to cite. On a system "
            "without Dex the report may only say what Dex offers for each "
            "job, never that the person is behind."
        )
    return tuple(errors)


def _render_job_axis(ledger: ComparisonLedger) -> str:
    return canonical_job_axis_block(ledger)


def canonical_release_gap_block(ledger: ComparisonLedger) -> str:
    """Headline release-gap story: behind, Unknown, or honestly no claim.

    Persona A's whole point — "your install is N releases behind, and the gap
    concentrates in these areas" — was computed only at compare time and never
    surfaced before the appendix, and when lineage could not be established
    the report said nothing at all. This block is the fix, and like
    :func:`canonical_coverage_block` it is rendered from the ledger alone so
    equivalent ledgers render it byte-identically. It speaks release
    identifiers, counts, and signed family titles only — never a label, path,
    or other content from the inspected system — and it always says
    *something*: a Verified gap with its honest lower bound, a loud priced
    Unknown naming the one observation that would establish the distance, or
    an explicit refusal to claim anything. What a named area would do for the
    person is quoted only from its signed family ``outcome`` (carried on the
    family-map row and in the what-changed section below), never invented.
    """

    lines = ["## Where your install stands"]
    distance = ledger.version_distance
    if distance is not None:
        releases = len(distance.newer_release_ids)
        families = sorted(
            distance.families,
            key=lambda item: (
                -(len(item.introduced_member_ids) + len(item.changed_member_ids)),
                item.family_id,
            ),
        )
        lines.append(
            f"Your install identifies Dex Core {distance.inspected_version} "
            "(Verified: your own release evidence, cited in the appendix); the "
            f"signed catalogue describes {distance.current_version}. The signed "
            f"catalogue names {releases} {_plural(releases, 'release')} newer than "
            f"yours, so your install is at least {releases} "
            f"{_plural(releases, 'release')} behind. The gap concentrates in "
            f"{len(families)} signed capability {_plural(len(families), 'area')}:"
        )
        for family in families:
            newer = len(family.introduced_member_ids)
            changed = len(family.changed_member_ids)
            parts: list[str] = []
            if newer:
                parts.append(
                    f"{newer} signed {_plural(newer, 'capability', 'capabilities')} "
                    "newer than your release"
                )
            if changed:
                parts.append(
                    f"{changed} signed {_plural(changed, 'capability', 'capabilities')} "
                    "changed since it"
                )
            lines.append(
                f"- {family.title} (`{family.family_id}`): " + " and ".join(parts) + "."
            )
        lines.append(
            "Each named area keeps its own row in the deterministic family map "
            "(`dex-lens diagnosis map`), and what each area does is quoted from "
            "its signed outcome in ‘What has changed since your identified Dex "
            "release’ below — the signed catalogue's own words, nothing invented."
        )
        return "\n".join(lines) + "\n"
    lineage_observed = any(
        item.kind is ObservationKind.RELEASE and item.identity == "dex-core"
        for item in ledger.local_entries
    )
    if not lineage_observed:
        # Dex is not installed here, so there is no distance to be Unknown
        # about. Asking this person to approve a folder holding a Dex release
        # file is a dead end — the file cannot exist (AGENTS.md F8). The job
        # axis carries their comparison, framed as a loan.
        lines.append(
            "You don't have Dex installed, so there is no version to compare "
            "and nothing here says you are behind. What Dex offers is set out "
            "job by job below — things you could take, not things you are "
            "missing."
        )
        return "\n".join(lines) + "\n"
    if not ledger.family_entries:
        lines.append(
            "How far this install stands behind the current Dex release is "
            "Unknown. Your snapshot identifies a Dex Core release, but this "
            "catalogue signs no capability-family contract, so no per-family "
            "release gap is derivable against it. Nothing here claims your "
            "install is behind or current."
        )
        return "\n".join(lines) + "\n"
    # Dex is present and something stopped the distance deriving. This is the
    # one population for whom naming the release file is the right ask, and
    # the claim stays refused rather than softened into a bland non-claim.
    lines.append(
        "How far this install stands behind the current Dex release is "
        "Unknown. Dex is installed here — the approved snapshot carries its "
        "release record — but no signed release gap was derivable: the "
        "release may not be readable from the snapshot, it may match the "
        "catalogue's own, the release evidence may conflict, or Dex's signed "
        "release history may name no family-level change since it. Nothing here "
        "claims your install is behind or current. A readable Dex Core "
        "release file (a `.dex-version` file or a `CHANGELOG.md` naming its "
        "version) is what establishes it. That is the whole price: approve "
        "the folder that holds it and run again, and the distance is worked "
        "out from Dex's own signed release history alone."
    )
    return "\n".join(lines) + "\n"


def canonical_fact_block(ledger: ComparisonLedger) -> str:
    """Exact factual block a report must embed under Coverage and limits."""

    summary = LedgerSummary.from_ledger(ledger)
    local_total = len(ledger.local_entries)
    local_mapped = sum(bool(item.mapped_catalogue_ids) for item in ledger.local_entries)
    local_unassessed = sum(
        item.disposition is Disposition.NOT_ASSESSED for item in ledger.local_entries
    )
    mcp_server_count = len(ledger.mcp_tools_by_server)
    mcp_tool_count = sum(item.declared_tool_count for item in ledger.mcp_tools_by_server)
    complete_mcp_servers = sum(
        item.inventory_status == "complete" for item in ledger.mcp_tools_by_server
    )
    sampled_mcp_servers = mcp_server_count - complete_mcp_servers
    published_mcp_tools = sum(len(item.tools) for item in ledger.mcp_tools_by_server)
    matched_components = sum(
        len(item.matched_components) for item in ledger.family_entries
    )
    unresolved_components = sum(
        len(item.unresolved_components) for item in ledger.family_entries
    )
    return (
        f"- Record digest: {canonical_ledger_digest(ledger)}\n"
        + summary.canonical_markdown()
        + f"- Local observations: {local_total} captured; {local_mapped} mapped; "
        + f"{local_unassessed} "
        + ("remains" if local_unassessed == 1 else "remain")
        + " not assessed.\n"
        + f"- Signed MCP inventory: {mcp_tool_count} declared "
        + f"{_plural(mcp_tool_count, 'tool')} across {mcp_server_count} "
        + f"{_plural(mcp_server_count, 'server')}; {complete_mcp_servers} complete "
        + f"{_plural(complete_mcp_servers, 'inventory', 'inventories')}; "
        + f"{sampled_mcp_servers} sampled "
        + f"{_plural(sampled_mcp_servers, 'inventory', 'inventories')}"
        + (
            f" ({published_mcp_tools} published examples; remaining tool identities Unknown)"
            if sampled_mcp_servers
            else ""
        )
        + ".\n"
        + f"- Significant-family components: {matched_components} exact "
        + f"{_plural(matched_components, 'match', 'matches')}; {unresolved_components} "
        + ("remains" if unresolved_components == 1 else "remain")
        + " Unknown.\n"
    )


def _appendix_catalogue_row(item: object) -> dict[str, object]:
    return {
        "catalogue_id": item.catalogue_id,
        "capability_id": item.capability_id,
        "disposition": item.disposition.value,
        "evidence_references": sorted(item.evidence_references),
        "method_compared": item.method_compared,
        "reason": item.reason,
    }


def _appendix_local_row(item: object) -> dict[str, object]:
    return {
        "observation_id": item.observation_id,
        "kind": item.kind.value,
        "identity": item.identity,
        "configuration_state": item.configuration_state.value,
        "runtime_state": item.runtime_state.value,
        "health_state": item.health_state.value,
        "disposition": item.disposition.value,
        "mapped_catalogue_ids": list(item.mapped_catalogue_ids),
        "mapped_capability_ids": list(item.mapped_capability_ids),
        "evidence_references": list(item.evidence_references),
        "reason": item.reason,
        "limitation": item.limitation,
    }


def _appendix_mcp_tools(item: object) -> dict[str, object]:
    return {
        "declared_tool_count": item.declared_tool_count,
        "inventory_status": item.inventory_status,
        "server_id": item.server_id,
        "server_name": item.server_name,
        "tools": list(item.tools),
    }


def _family_component_row(item: object) -> dict[str, object]:
    return {
        "component_reference": item.component_reference,
        "observation_ids": list(item.observation_ids),
        "evidence_references": list(item.evidence_references),
        "match_bases": [basis.value for basis in item.match_bases],
        "method_equivalent": item.method_equivalent,
    }


def _family_row(item: object) -> dict[str, object]:
    return {
        "family_id": item.family_id,
        "title": item.title,
        "outcome": item.outcome,
        "signed_availability": item.signed_availability.value,
        "available_member_ids": list(item.available_member_ids),
        "unavailable_member_ids": list(item.unavailable_member_ids),
        "recommendable_member_ids": list(item.recommendable_member_ids),
        "matched_components": [
            _family_component_row(component) for component in item.matched_components
        ],
        "matched_observation_ids": list(item.matched_observation_ids),
        "unresolved_components": list(item.unresolved_components),
        "evidence_references": list(item.evidence_references),
        "disposition": item.disposition.value,
        "reason": item.reason,
    }


def _family_delta_row(item: object) -> dict[str, object]:
    return {
        "available_member_ids": list(item.available_member_ids),
        "availability": item.availability.value,
        "changed_member_ids": list(item.changed_member_ids),
        "current_version": item.current_version,
        "family_id": item.family_id,
        "inspected_version": item.inspected_version,
        "introduced_member_ids": list(item.introduced_member_ids),
        "outcome": item.outcome,
        "recommendable_member_ids": list(item.recommendable_member_ids),
        "title": item.title,
        "unavailable_member_ids": list(item.unavailable_member_ids),
    }


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _family_availability_phrase(value: str) -> str:
    return {
        "available": "Dex currently offers the full family",
        "partial": "Dex currently offers part of this family",
        "unavailable": "Dex does not currently offer this family for recommendation",
    }[value]


def _family_disposition_phrase(value: str) -> str:
    return {
        "not-assessed": "the local evidence still needs a manual review",
        "unresolved": "no exact local overlap was proven",
        "partial-overlap": "some exact local overlap was found",
        "overlap-observed": "all published building blocks have exact local overlap",
        "not-recommendable": "this release does not make the family recommendable",
        "postdates-install": (
            "every building block here arrived after your install's own "
            "release, so this install cannot carry them"
        ),
    }[value]


def _render_family_coverage(ledger: ComparisonLedger) -> str:
    lines = ["## Significant capability coverage"]
    if not ledger.family_entries:
        lines.append("No signed significant-family contract was present in this catalogue.")
        return "\n".join(lines) + "\n"
    for family in ledger.family_entries:
        matched = len(family.matched_components)
        unresolved = len(family.unresolved_components)
        # A family proven un-carryable by release history is evidence of
        # absence; calling its components "Unknown" in the same breath
        # contradicted the expectations block one section down.
        if family.disposition is FamilyAssessmentDisposition.POSTDATES_INSTALL:
            unknown = (
                f"{unresolved} {_plural(unresolved, 'component')} "
                "cannot be on this install"
            )
        elif unresolved:
            unknown = (
                f"{unresolved} {_plural(unresolved, 'component')} "
                f"{'remains' if unresolved == 1 else 'remain'} Unknown"
            )
        else:
            unknown = "no signed components remain Unknown"
        lines.append(
            f"- {family.title} (`{family.family_id}`): {matched} exact "
            f"{_plural(matched, 'component')} matched; {unknown}. "
            f"{_family_availability_phrase(family.signed_availability.value)}; "
            f"{_family_disposition_phrase(family.disposition.value)}."
        )
    return "\n".join(lines) + "\n"


def _render_wow_expectations(ledger: ComparisonLedger) -> str:
    """Render every expectation row visibly, one plain line each.

    A family-free catalogue yields fourteen loud ``not-gated`` rows, so the
    absence of a release-gap story always arrives with the sentence saying
    why — never as silence.  Every line is engine-authored fixed wording
    joined to engine-derived states; no host text enters this section.
    """

    if not ledger.expectations:
        return ""
    lines = ["## Significant capability expectations"]
    lines.extend(
        f"- `{item.family_id}` — {item.state.value}: {item.reason}"
        for item in ledger.expectations
    )
    return "\n".join(lines) + "\n"


def _validate_ledger_insights(ledger: ComparisonLedger) -> None:
    """Refuse an insight citing evidence this ledger does not hold.

    Checking only for empty ``evidence_ids`` was a tautology:
    ``GroundedInsight.evidence_ids`` already carries ``Field(min_length=1)``,
    so that branch could never be reached. The claim worth refusing is the one
    that cites an identity no disposition in this ledger records, because the
    rendered report tells the reader the exact references are in the appendix.
    """

    held = ledger_evidence_identities(ledger)
    for insight in (
        *ledger.strengths,
        *ledger.reciprocal_lessons,
        *ledger.workflow_insights,
    ):
        cited = {*insight.evidence_ids, *insight.observation_ids}
        if not cited <= held:
            raise ValueError("insight cites evidence the ledger does not hold")


def _render_grounded_strengths(ledger: ComparisonLedger) -> str:
    if not ledger.strengths:
        # A guided run ran the strength packet, and by construction only
        # observations the person authored can ground a strength — stock Dex
        # and assistant-shipped files never qualify.  An empty result is
        # therefore a real answer and gets the honest sentence, never a
        # silently missing section or padding.  Inventory-only runs never
        # assessed strengths, so they render nothing here.
        if ledger.work_audit is not None:
            return (
                "## What is especially strong here\n"
                "Nothing beyond stock Dex cleared the strength bar.\n"
            )
        return ""
    lines = ["## What is especially strong here"]
    for insight in ledger.strengths:
        lines.extend(
            (
                f"### {insight.title}",
                insight.explanation,
                _render_human_evidence(insight.evidence_ids),
            )
        )
    return "\n".join(lines) + "\n"


def _render_ranked_recommendations(ledger: ComparisonLedger) -> str:
    ranked = ledger.ranked_recommendations
    if not ranked:
        return ""
    by_rank = {item.rank: item for item in ranked}
    lines: list[str] = []
    if 1 in by_rank:
        item = by_rank[1]
        lines.extend(
            (
                "## The best first move",
                f"### `{item.catalogue_id}`",
                item.reason,
                _render_human_evidence(item.evidence_ids),
            )
        )
    next_items = tuple(by_rank[rank] for rank in (2, 3) if rank in by_rank)
    if next_items:
        lines.append("## Next most useful")
        for item in next_items:
            lines.extend(
                (
                    f"### `{item.catalogue_id}`",
                    item.reason,
                    _render_human_evidence(item.evidence_ids),
                )
            )
    also = tuple(item for item in ranked if item.rank >= 4)
    if also:
        lines.append("## Also worth considering")
        for item in also:
            lines.extend(
                (
                    f"### `{item.catalogue_id}`",
                    item.reason,
                    _render_human_evidence(item.evidence_ids),
                )
            )
    return "\n".join(lines) + "\n"


def _render_workflow_connections(ledger: ComparisonLedger) -> str:
    if not ledger.workflow_insights:
        return ""
    lines = ["## Connections Lens noticed"]
    for insight in ledger.workflow_insights:
        lines.extend(
            (
                f"### {insight.title}",
                insight.explanation,
                _render_human_evidence(insight.evidence_ids),
            )
        )
    return "\n".join(lines) + "\n"


def _render_strengths(ledger: ComparisonLedger) -> str:
    matched_observation_ids = {
        observation_id
        for family in ledger.family_entries
        for observation_id in family.matched_observation_ids
    }
    matched_components = sum(len(family.matched_components) for family in ledger.family_entries)
    matched_families = sum(bool(family.matched_components) for family in ledger.family_entries)
    kinds = {
        entry.kind
        for entry in ledger.local_entries
        if entry.observation_id in matched_observation_ids
    }
    working_observation_ids = {
        entry.observation_id
        for entry in ledger.local_entries
        if entry.observation_id in matched_observation_ids
        and (
            entry.runtime_state is RuntimeState.OUTCOME_VERIFIED
            or entry.health_state is HealthState.HEALTHY
        )
    }
    lines = ["## What is working especially well"]
    if matched_observation_ids:
        building_count = len(matched_observation_ids)
        if not working_observation_ids:
            subject = "the matched building block" if building_count == 1 else (
                f"the {building_count} matched building blocks"
            )
            verb = "has" if building_count == 1 else "have"
            lines.append(
                "This approved snapshot cannot prove that a capability is working "
                f"especially well because {subject} {verb} no verified outcome or "
                "health evidence."
            )
            lines.append("## What is clearly built")
        lines.append(
            f"Your approved snapshot contains {building_count} evidence-bound "
            f"{_plural(building_count, 'building block')} across {len(kinds)} observed "
            f"{_plural(len(kinds), 'capability type')}, creating {matched_components} exact "
            f"signed {_plural(matched_components, 'component overlap')} across "
            f"{matched_families} {_plural(matched_families, 'outcome family', 'outcome families')}."
        )
        if working_observation_ids:
            lines.append(
                "This snapshot provides verified outcome or health evidence for "
                f"{len(working_observation_ids)} matched "
                f"{_plural(len(working_observation_ids), 'building block')}. An exact "
                "signed match means the identity was verified from Dex's release."
            )
        else:
            lines.append(
                "These exact configuration matches are meaningful evidence of what you "
                "have assembled, not evidence that it runs well."
            )
        strongest = sorted(
            (family for family in ledger.family_entries if family.matched_components),
            key=lambda family: (
                -len(family.matched_components)
                / max(1, len(family.matched_components) + len(family.unresolved_components)),
                -len(family.matched_components),
                family.family_id,
            ),
        )[:3]
        for family in strongest:
            matched = len(family.matched_components)
            total = matched + len(family.unresolved_components)
            suffix = (
                "That is evidence of real foundations in this area."
                if set(family.matched_observation_ids) & working_observation_ids
                else "That proves a local configuration match, not a working outcome."
            )
            lines.append(
                f"- {family.title}: {matched} of {total} published "
                f"{_plural(total, 'building block')} have an exact local match. {suffix}"
            )
        lines.append(
            "This evidence does not establish method equivalence, runtime quality, or outcomes."
        )
    else:
        lines.append(
            "No significant-family strength cleared the exact evidence bar. "
            "Captured observations remain useful, but their relationship to these outcomes "
            "is Unknown."
        )
    titles = {item.capability_id: item.title for item in ledger.capabilities}
    reviewed = sorted(
        (
            item
            for item in ledger.entries
            if item.disposition in {Disposition.STRONG_HERE, Disposition.SHARED}
        ),
        key=lambda item: item.catalogue_id,
    )
    for finding in reviewed:
        lines.extend(
            (
                f"### {titles.get(finding.capability_id, finding.capability_id)} "
                f"(`{finding.catalogue_id}`)",
                finding.reason,
                _render_human_evidence(finding.evidence_references),
            )
        )
    return "\n".join(lines) + "\n"


def _render_reciprocal_learning(ledger: ComparisonLedger) -> str:
    body = _render_disposition_findings(
        ledger,
        heading="What Dex should learn from you",
        dispositions=frozenset({Disposition.DEX_SHOULD_LEARN}),
        empty_message="",
    ).splitlines()
    reviewed_count = sum(
        item.disposition is Disposition.DEX_SHOULD_LEARN for item in ledger.entries
    )
    answer = ledger.reciprocal_answer
    if reviewed_count and (
        "Unknown" in answer or "No transferable method" in answer
    ):
        answer = (
            "The automatic identity match alone cannot prove a transferable method. "
            f"The evidence-reviewed {_plural(reviewed_count, 'pattern')} below "
            "cleared that stricter bar."
        )
    lines = [body[0], answer]
    for insight in ledger.reciprocal_lessons:
        lines.extend(
            (
                f"### {insight.title}",
                insight.explanation,
                _render_human_evidence(insight.evidence_ids),
            )
        )
    lines.extend(line for line in body[1:] if line)
    return "\n".join(lines) + "\n"


def _render_unique_to_you(ledger: ComparisonLedger) -> str:
    """List the engine-computed catalogue-unmatched items, grouped by type.

    The list itself is engine-derived (the observation origin axis), so the
    host can read it aloud but cannot flatter by invention; it is the
    deterministic candidate list for the reciprocal share-back offers, and
    nothing is ever shared without the person approving exact words in a
    separate flow.

    Two voice rules, both founder decisions (2026-09-08, AGENTS.md F7): the
    section claims possession, never personal authorship — "part of your
    setup" is true for an item the person wrote, imported, or merely kept
    running, while "yours alone" praised Dex's own retired stock back to the
    person on every stale install; and when the run knows the install is
    behind, it says plainly that some of these may be older Dex, because no
    local signal can tell.  Items render grouped by what they are: a hundred
    identical boilerplate rows is a wall, not a map.
    """

    if not ledger.unique_to_you:
        return ""
    local_by_id = {entry.observation_id: entry for entry in ledger.local_entries}
    rows = sorted(
        (local_by_id[observation_id] for observation_id in ledger.unique_to_you),
        key=lambda entry: (entry.kind.value, entry.identity),
    )
    count = len(rows)
    lines = [
        "## Unique to you",
        (
            f"{count} {_plural(count, 'item')} in your system "
            f"{_plural(count, 'matches', 'match')} nothing in today's signed Dex "
            "catalogue and did not arrive with the assistant (engine-derived "
            "identity matching, not judgement). They are part of the setup you "
            "have put together — written by you, brought in from elsewhere, or "
            "kept running by you — and they are the candidates worth offering "
            "back as ideas, only ever in words you approve first."
        ),
    ]
    if ledger.version_distance is not None:
        lines.append(
            "One caution: your install is behind the catalogue this run "
            "compared against, so some of these may have shipped with the older "
            "Dex you installed. Only Dex publishing the identities it used to "
            "ship would tell exactly which."
        )
    by_kind: dict[str, list[str]] = {}
    for entry in rows:
        by_kind.setdefault(entry.kind.value, []).append(entry.identity)
    lines.extend(
        f"- {kind_value}s ({len(identities)}): "
        + ", ".join(f"`{identity}`" for identity in identities)
        for kind_value, identities in sorted(by_kind.items())
    )
    lines.append(
        "Each item's exact evidence references are in the full record appendix."
    )
    return "\n".join(lines) + "\n"


def _render_version_distance(ledger: ComparisonLedger) -> str:
    distance = ledger.version_distance
    if distance is None:
        return ""
    lines = [
        "## What has changed since your identified Dex release",
        (
            f"The approved snapshot identifies Dex Core {distance.inspected_version}; "
            f"the signed catalogue describes {distance.current_version}. The rows below "
            "come only from signed skill `since_release` and `changed_in` fields. They do "
            "not infer release history for MCP servers, scheduled work or engines; families "
            "without a signed release history are omitted, not treated as unchanged."
        ),
    ]
    for family in sorted(distance.families, key=lambda item: item.family_id):
        lines.extend((f"### {family.title}", family.outcome))
        if family.introduced_member_ids:
            introduced = ", ".join(f"`{item}`" for item in family.introduced_member_ids)
            lines.append(f"New signed skill entries: {introduced}.")
        if family.changed_member_ids:
            changed = ", ".join(f"`{item}`" for item in family.changed_member_ids)
            lines.append(f"Signed skill entries changed after your release: {changed}.")
        availability = _family_availability_phrase(family.availability.value)
        lines.append(
            f"Current signed family state: {availability}."
        )
    return "\n".join(lines) + "\n"


def _render_disposition_findings(
    ledger: ComparisonLedger,
    *,
    heading: str,
    dispositions: frozenset[Disposition],
    empty_message: str,
) -> str:
    titles = {item.capability_id: item.title for item in ledger.capabilities}
    findings = sorted(
        (item for item in ledger.entries if item.disposition in dispositions),
        key=lambda item: item.catalogue_id,
    )
    lines = [f"## {heading}"]
    if not findings:
        lines.append(empty_message)
        return "\n".join(lines) + "\n"
    for finding in findings:
        title = titles.get(finding.capability_id, finding.capability_id)
        lines.extend(
            (
                f"### {title} (`{finding.catalogue_id}`)",
                finding.reason,
                _render_human_evidence(finding.evidence_references),
            )
        )
    return "\n".join(lines) + "\n"


def _render_human_evidence(references: tuple[str, ...]) -> str:
    count = len(references)
    return (
        f"Evidence: {count} approved {_plural(count, 'observation')}; exact references "
        "are in the appendix."
    )


def _render_recommendations(ledger: ComparisonLedger) -> str:
    """Worth-borrowing findings, minus the ones the ranked list already told.

    A finding that is also a ranked move already carries its full reason and
    evidence a few lines up; repeating it verbatim here read as noise to the
    first real reader (RISK-FIRST-READ-REPORT-VOICE-2026-09-08). The section
    still names those entries so the borrow list stays complete, and findings
    the ranking does not carry keep their full rendering.
    """

    titles = {item.capability_id: item.title for item in ledger.capabilities}
    findings = sorted(
        (
            item
            for item in ledger.entries
            if item.disposition is Disposition.WORTH_BORROWING
        ),
        key=lambda item: item.catalogue_id,
    )
    lines = ["## Worth borrowing from Dex"]
    if not findings:
        lines.append("No Dex addition cleared the evidence bar this time.")
        return "\n".join(lines) + "\n"
    ranked_ids = {item.catalogue_id for item in ledger.ranked_recommendations}
    already_ranked = tuple(
        item for item in findings if item.catalogue_id in ranked_ids
    )
    if already_ranked:
        named = ", ".join(f"`{item.catalogue_id}`" for item in already_ranked)
        lines.append(
            f"Already covered by the ranked moves above: {named}."
        )
    for finding in findings:
        if finding.catalogue_id in ranked_ids:
            continue
        title = titles.get(finding.capability_id, finding.capability_id)
        lines.extend(
            (
                f"### {title} (`{finding.catalogue_id}`)",
                finding.reason,
                _render_human_evidence(finding.evidence_references),
            )
        )
    return "\n".join(lines) + "\n"


def _render_rejections(ledger: ComparisonLedger) -> str:
    return _render_disposition_findings(
        ledger,
        heading="Considered and rejected",
        dispositions=frozenset({Disposition.NOT_RELEVANT}),
        empty_message="No catalogue entry was explicitly ruled out in this run.",
    )


def _render_what_was_read(ledger: ComparisonLedger) -> str:
    kinds = {item.kind for item in ledger.local_entries}
    return (
        "## What I read\n"
        f"- {len(ledger.local_entries)} consented local "
        f"{_plural(len(ledger.local_entries), 'observation')} across {len(kinds)} "
        f"{_plural(len(kinds), 'capability type')}.\n"
        f"- {len(ledger.entries)} entries from the exact signed Dex catalogue recorded "
        f"by digest `{ledger.catalogue_sha256}`.\n"
        "- The complete evidence-bound accounting is in the full record appendix below.\n"
    )


def _render_fragility(ledger: ComparisonLedger) -> str:
    return _render_disposition_findings(
        ledger,
        heading="Fragility and contradictions",
        dispositions=frozenset({Disposition.FRAGILE_OR_CONTRADICTORY}),
        empty_message=(
            "No evidence-backed contradiction cleared the bar. That is Unknown, not a "
            "clean bill of health."
        ),
    )


def canonical_ledger_appendix(ledger: ComparisonLedger) -> str:
    """Render every ledger row as deterministic JSON lines.

    The appendix is intentionally machine-readable and separate from the
    short human summary.  Rows are sorted by catalogue identity, then local
    observation identity, so equivalent ledgers produce byte-identical text.
    """

    lines = [
        "## Complete record appendix",
        "<!-- canonical-ledger-appendix -->",
        "### Catalogue entries",
    ]
    lines.extend(
        json.dumps(
            {"row_type": "catalogue", **_appendix_catalogue_row(item)},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for item in sorted(ledger.entries, key=lambda item: item.catalogue_id)
    )
    lines.append("### Significant capability families")
    lines.extend(
        json.dumps(
            {"row_type": "family", **_family_row(item)},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for item in sorted(ledger.family_entries, key=lambda item: item.family_id)
    )
    if ledger.job_axis:
        # Rendered only on a non-lineage run, so lineage appendixes stay
        # byte-identical to what they were before the job axis existed.
        lines.append("### Signed job coverage")
        lines.extend(
            json.dumps(
                {"row_type": "job-coverage", **_job_axis_row(item)},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            for item in ledger.job_axis
        )
    lines.append("### Proven release changes")
    if ledger.version_distance is not None:
        lines.extend(
            json.dumps(
                {
                    "row_type": "version-distance",
                    **_family_delta_row(item),
                    "evidence_references": list(
                        ledger.version_distance.evidence_references
                    ),
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            for item in sorted(
                ledger.version_distance.families,
                key=lambda item: item.family_id,
            )
        )
    lines.append("### Signed MCP inventories by server")
    lines.extend(
        json.dumps(
            {"row_type": "mcp-tools", **_appendix_mcp_tools(item)},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for item in sorted(ledger.mcp_tools_by_server, key=lambda item: item.server_id)
    )
    lines.append("### Local observations")
    lines.extend(
        json.dumps(
            {"row_type": "local", **_appendix_local_row(item)},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for item in sorted(ledger.local_entries, key=lambda item: item.observation_id)
    )
    return "\n".join(lines) + "\n"


def ledger_appendix_errors(
    report_markdown: str,
    ledger: ComparisonLedger,
) -> tuple[str, ...]:
    """Reject missing, duplicated, altered, or reordered appendix rows."""

    marker = "## Complete record appendix\n"
    if report_markdown.count(marker) != 1:
        return ("report ledger appendix must contain exactly one complete section",)
    start = report_markdown.find(marker)
    if start < 0:
        return ("report is missing the complete ledger appendix",)
    end = report_markdown.find("\n## ", start + len(marker))
    # ``render_markdown`` leaves one blank line before the following section;
    # exclude that separator while comparing the exact appendix bytes.
    actual = report_markdown[start:] if end < 0 else report_markdown[start:end]
    expected = canonical_ledger_appendix(ledger)
    if actual != expected:
        return ("report ledger appendix rows are missing, altered, duplicated, or reordered",)
    return ()


def ledger_derived_fact_errors(report_markdown: str, ledger: ComparisonLedger) -> tuple[str, ...]:
    """Reject reports that omit, alter, or contradict ledger-derived facts."""

    expected = canonical_fact_block(ledger)
    if expected not in report_markdown:
        return ("report is missing exact ledger-derived facts",)

    remaining = report_markdown.replace(expected, "", 1)
    summary = LedgerSummary.from_ledger(ledger)
    allowed = {
        summary.total,
        summary.assessed,
        summary.unknown,
        *summary.by_disposition.values(),
    }
    if any(int(match.group(1)) not in allowed for match in _COVERAGE_CLAIM.finditer(remaining)):
        return ("report contradicts ledger-derived facts",)
    return ()
