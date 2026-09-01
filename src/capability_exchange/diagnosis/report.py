"""Ledger-derived diagnosis facts. Markdown cannot invent its own totals."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from contextvars import ContextVar
from typing import Self

from pydantic import ConfigDict, Field, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.comparison import ComparisonLedger, Disposition
from capability_exchange.diagnosis.finding import Finding
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


def _canonical_ledger_payload(ledger: ComparisonLedger) -> dict[str, object]:
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
                "evidence_references": list(item.evidence_references),
                "method_compared": item.method_compared,
                "reason": item.reason,
            }
            for item in sorted(ledger.entries, key=lambda item: item.catalogue_id)
        ],
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
                "operational_state": item.operational_state.value,
                "reason": item.reason,
            }
            for item in sorted(ledger.local_entries, key=lambda item: item.observation_id)
        ],
        "reciprocal_answer": ledger.reciprocal_answer,
    }


def canonical_ledger_digest(ledger: ComparisonLedger) -> str:
    """Return a stable SHA-256 binding for one exact comparison ledger."""

    encoded = json.dumps(
        _canonical_ledger_payload(ledger),
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
    ) -> Self:
        expected = canonical_ledger_digest(ledger)
        supplied = (
            ledger_sha256 if ledger_sha256.startswith("sha256:") else f"sha256:{ledger_sha256}"
        )
        if supplied != expected:
            raise ValueError("report must bind the exact comparison ledger")
        token = _FROM_RESULT.set(True)
        try:
            return cls(
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
            "## Coverage and limits\n"
            f"{block}"
            f"{extra}"
            f"\n{appendix}"
            "\n"
            f"{self._render_decisions()}"
            "\n"
            f"{self._render_close()}"
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

    def _render_close(self) -> str:
        strongest = (
            self.strongest_findings[0].practical_implication
            if self.strongest_findings
            else "No grounded strength cleared the evidence bar."
        )
        learn = (
            self.reciprocal_findings[0].practical_implication
            if self.reciprocal_findings
            else "No transferable method cleared the evidence bar."
        )
        first_move = (
            self.strongest_findings[0].recommended_next_move
            if self.strongest_findings
            else "No first move cleared the bar."
        )
        return (
            "## What happens next\n"
            f"- Already doing: {strongest}\n"
            f"- Dex should learn: {learn}\n"
            f"- First move: {first_move}\n"
            "- Report location: This report has not been saved yet.\n"
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
    return (
        f"- Ledger digest: {canonical_ledger_digest(ledger)}\n"
        + summary.canonical_markdown()
    )


def _appendix_catalogue_row(item: object) -> dict[str, object]:
    return {
        "catalogue_id": item.catalogue_id,
        "capability_id": item.capability_id,
        "disposition": item.disposition.value,
        "evidence_references": list(item.evidence_references),
        "method_compared": item.method_compared,
        "reason": item.reason,
    }


def _appendix_local_row(item: object) -> dict[str, object]:
    return {
        "observation_id": item.observation_id,
        "kind": item.kind.value,
        "identity": item.identity,
        "operational_state": item.operational_state.value,
        "disposition": item.disposition.value,
        "mapped_catalogue_ids": list(item.mapped_catalogue_ids),
        "mapped_capability_ids": list(item.mapped_capability_ids),
        "evidence_references": list(item.evidence_references),
        "reason": item.reason,
        "limitation": item.limitation,
    }


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
