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

__all__ = [
    "LedgerSummary",
    "canonical_fact_block",
    "canonical_ledger_digest",
    "ledger_derived_fact_errors",
]

_FROM_LEDGER = ContextVar("_ledger_summary_from_ledger", default=False)
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


def canonical_fact_block(ledger: ComparisonLedger) -> str:
    """Exact factual block a report must embed under Coverage and limits."""

    summary = LedgerSummary.from_ledger(ledger)
    return (
        f"- Ledger digest: {canonical_ledger_digest(ledger)}\n"
        + summary.canonical_markdown()
    )


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
