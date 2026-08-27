"""Complete, evidence-led two-way comparison with a verified catalogue."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.evidence.item import reference_rejection_reason

__all__ = [
    "CatalogueDisposition",
    "ComparisonLedger",
    "Disposition",
    "HumanCapability",
]

_ID_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,159}$"
_HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NO_TRANSFERABLE_METHOD = "No transferable method cleared the evidence bar."


class Disposition(StrEnum):
    """Closed answer for one Dex catalogue entry in one person's system."""

    STRONG_HERE = "strong-here"
    SHARED = "shared"
    WORTH_BORROWING = "worth-borrowing"
    DEX_SHOULD_LEARN = "dex-should-learn"
    FRAGILE_OR_CONTRADICTORY = "fragile-or-contradictory"
    NOT_RELEVANT = "not-relevant"
    NOT_ASSESSED = "not-assessed"


class CatalogueDisposition(InventoriedModel):
    """One explicit, evidenced disposition for one signed catalogue entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalogue_id: str = Field(pattern=_ID_PATTERN)
    disposition: Disposition
    capability_id: str = Field(pattern=_ID_PATTERN)
    evidence_references: tuple[str, ...] = ()
    method_compared: bool = False
    reason: str = Field(min_length=1, max_length=600)

    @field_validator("evidence_references")
    @classmethod
    def _references_are_bounded_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("duplicate evidence reference on catalogue disposition")
        for value in values:
            if not value.strip():
                raise ValueError("evidence references must be non-empty")
            reason = reference_rejection_reason(value)
            if reason is not None:
                raise ValueError(reason)
        return values

    @field_validator("reason")
    @classmethod
    def _reason_is_one_safe_line(cls, value: str) -> str:
        if _CONTROL.search(value):
            raise ValueError("a disposition reason must be one bounded line")
        return value

    @model_validator(mode="after")
    def _claims_have_evidence(self) -> Self:
        grounded = {
            Disposition.STRONG_HERE,
            Disposition.SHARED,
            Disposition.WORTH_BORROWING,
            Disposition.DEX_SHOULD_LEARN,
            Disposition.FRAGILE_OR_CONTRADICTORY,
        }
        if self.disposition in grounded and not self.evidence_references:
            raise ValueError("a scored disposition requires evidence")
        if self.disposition is Disposition.SHARED and not self.method_compared:
            raise ValueError("shared requires method evidence, not name similarity")
        return self


class HumanCapability(InventoriedModel):
    """One human-meaningful capability spanning local and Dex identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(pattern=_ID_PATTERN)
    title: str = Field(min_length=1, max_length=160)
    job_ids: tuple[str, ...]
    catalogue_ids: tuple[str, ...]
    person_observation_ids: tuple[str, ...]

    @field_validator("job_ids", "catalogue_ids", "person_observation_ids")
    @classmethod
    def _identity_lists_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("human capability identity lists must not contain duplicates")
        for value in values:
            if re.fullmatch(_ID_PATTERN, value) is None:
                raise ValueError(f"{value!r} is not a bounded capability identity")
        return values


def _model_validation_error(message: str, input_value: object) -> ValidationError:
    return ValidationError.from_exception_data(
        "ComparisonLedger",
        [
            {
                "type": "value_error",
                "loc": (),
                "input": input_value,
                "ctx": {"error": ValueError(message)},
            }
        ],
    )


class ComparisonLedger(InventoriedModel):
    """Complete accounting for the verified catalogue and reciprocal value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalogue_version: int = Field(ge=1)
    catalogue_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)
    capabilities: tuple[HumanCapability, ...]
    entries: tuple[CatalogueDisposition, ...] = Field(min_length=1)
    reciprocal_answer: str = Field(min_length=1, max_length=1000)

    @field_validator("reciprocal_answer")
    @classmethod
    def _reciprocal_answer_is_bounded_text(cls, value: str) -> str:
        if _CONTROL.search(value):
            raise ValueError("reciprocal answer must be one bounded line")
        return value

    @model_validator(mode="after")
    def _bounded_and_unique(self) -> Self:
        recommendations = sum(
            item.disposition is Disposition.WORTH_BORROWING for item in self.entries
        )
        if recommendations > 3:
            raise ValueError("a report may recommend at most three Dex additions")
        entry_ids = [item.catalogue_id for item in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("comparison ledger contains a duplicate catalogue identity")
        capability_ids = [item.capability_id for item in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("comparison ledger contains a duplicate human capability identity")
        return self

    @classmethod
    def for_catalogue(
        cls,
        catalogue: CatalogueV2,
        *,
        catalogue_version: int,
        catalogue_sha256: str,
        capabilities: tuple[HumanCapability, ...],
        entries: tuple[CatalogueDisposition, ...],
        reciprocal_answer: str = _NO_TRANSFERABLE_METHOD,
    ) -> ComparisonLedger:
        """Validate a ledger against the exact verified catalogue identity set."""
        expected = {item.capability_id for item in catalogue.capabilities}
        actual = [item.catalogue_id for item in entries]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise _model_validation_error(
                "ledger entries must equal the verified catalogue identity set",
                actual,
            )
        unknown = sorted(
            {
                catalogue_id
                for capability in capabilities
                for catalogue_id in capability.catalogue_ids
                if catalogue_id not in expected
            }
        )
        if unknown:
            raise _model_validation_error(
                f"human capabilities reference unknown catalogue IDs: {', '.join(unknown)}",
                unknown,
            )
        known_capability_ids = {item.capability_id for item in capabilities}
        unassigned = sorted(
            {
                entry.capability_id
                for entry in entries
                if entry.capability_id != "unassigned"
                and entry.capability_id not in known_capability_ids
            }
        )
        if unassigned:
            raise _model_validation_error(
                f"ledger entries reference unknown human capability IDs: {', '.join(unassigned)}",
                unassigned,
            )
        return cls(
            catalogue_version=catalogue_version,
            catalogue_sha256=catalogue_sha256,
            capabilities=capabilities,
            entries=entries,
            reciprocal_answer=reciprocal_answer,
        )
