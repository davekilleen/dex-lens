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
from capability_exchange.diagnosis.observations import HealthState, RuntimeState
from capability_exchange.diagnosis.receipts import (
    DecisionState,
    RecommendationDecision,
    ShareReceipt,
    ShareState,
)
from capability_exchange.diagnosis.run import RunIdentity

__all__ = [
    "LedgerSummary",
    "ReportModel",
    "canonical_fact_block",
    "canonical_ledger_appendix",
    "canonical_ledger_digest",
    "canonical_ledger_payload",
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


def _home_relative_location(location: str) -> str:
    """Render a report location without naming the account that owns it.

    WO-022, decided 2026-09-03: the footer lives in the most shareable
    artifact Lens produces, and an absolute home path carries the person's
    username. A location under the home directory renders as ``~/…``;
    anywhere else is rendered as written.
    """

    try:
        return "~/" + Path(location).relative_to(Path.home()).as_posix()
    except ValueError:
        return location


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
            f"\n{_render_version_distance(ledger)}"
            f"\n{_render_grounded_strengths(ledger)}"
            f"\n{_render_strengths(ledger)}"
            f"\n{_render_reciprocal_learning(ledger)}"
            f"\n{_render_ranked_recommendations(ledger)}"
            f"\n{_render_recommendations(ledger)}"
            f"\n{_render_workflow_connections(ledger)}"
            f"\n{_render_rejections(ledger)}"
            f"\n{_render_fragility(ledger)}"
            "\n## Coverage and limits\n"
            f"{block}"
            f"{extra}"
            f"\n{_render_family_coverage(ledger)}"
            f"\n{appendix}"
            "\n"
            f"{self._render_decisions()}"
            "\n"
            f"{self._render_close(ledger)}"
        )

    def _render_decisions(self) -> str:
        lines = ["## What you decided"]
        if not self.decisions:
            lines.append("No decisions were on the table this time.")
            return "\n".join(lines) + "\n"
        for decision in self.decisions:
            fate = "offered" if decision.state is DecisionState.OFFERED else "taken"
            lines.append(f"- {decision.catalogue_id} — {fate}")
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
        report_location = (
            f"`{_home_relative_location(self._report_location)}`."
            if self._report_location is not None
            else "This report will be saved before the run closes."
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
        f"- Ledger digest: {canonical_ledger_digest(ledger)}\n"
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
    }[value]


def _render_family_coverage(ledger: ComparisonLedger) -> str:
    lines = ["## Significant capability coverage"]
    if not ledger.family_entries:
        lines.append("No signed significant-family contract was present in this catalogue.")
        return "\n".join(lines) + "\n"
    for family in ledger.family_entries:
        matched = len(family.matched_components)
        unresolved = len(family.unresolved_components)
        unknown = (
            f"{unresolved} {_plural(unresolved, 'component')} "
            f"{'remains' if unresolved == 1 else 'remain'} Unknown"
            if unresolved
            else "no signed components remain Unknown"
        )
        lines.append(
            f"- {family.title} (`{family.family_id}`): {matched} exact "
            f"{_plural(matched, 'component')} matched; {unknown}. "
            f"{_family_availability_phrase(family.signed_availability.value)}; "
            f"{_family_disposition_phrase(family.disposition.value)}."
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
            "without signed lineage are omitted, not treated as unchanged."
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
    return _render_disposition_findings(
        ledger,
        heading="Worth borrowing from Dex",
        dispositions=frozenset({Disposition.WORTH_BORROWING}),
        empty_message="No Dex addition cleared the evidence bar this time.",
    )


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
        "- The complete evidence-bound accounting is in the ledger appendix below.\n"
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
        "## Complete ledger appendix",
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

    marker = "## Complete ledger appendix\n"
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
