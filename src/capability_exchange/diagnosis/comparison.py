"""Complete, evidence-led two-way comparison with a verified catalogue."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    ObservationKind,
    OperationalState,
    observation_id_for,
)
from capability_exchange.evidence.item import reference_rejection_reason

__all__ = [
    "CatalogueDisposition",
    "ComparisonLedger",
    "Disposition",
    "HumanCapability",
    "LocalObservationDisposition",
]

_ID_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,159}$"
_HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_OBSERVATION_ID_PATTERN = r"^observation:sha256:[0-9a-f]{64}$"
_NO_TRANSFERABLE_METHOD = "No transferable method cleared the evidence bar."
_NO_LOCAL_PROPOSAL = "No specialist proposal cited this observation."

if TYPE_CHECKING:
    from capability_exchange.diagnosis.report import LedgerSummary


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


class LocalObservationDisposition(InventoriedModel):
    """One explicit, source-bound disposition for a local observation.

    The observation identity and operational facts are copied from the
    captured fingerprint.  Specialist mappings may add catalogue/capability
    identities, but cannot rewrite the source-bound observation itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str = Field(pattern=_OBSERVATION_ID_PATTERN)
    kind: ObservationKind
    identity: str = Field(pattern=_ID_PATTERN)
    operational_state: OperationalState
    disposition: Disposition = Disposition.NOT_ASSESSED
    mapped_catalogue_ids: tuple[str, ...] = ()
    mapped_capability_ids: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()
    reason: str = Field(default=_NO_LOCAL_PROPOSAL, min_length=1, max_length=600)
    limitation: str = Field(default=_NO_LOCAL_PROPOSAL, min_length=1, max_length=600)

    @field_validator("mapped_catalogue_ids", "mapped_capability_ids")
    @classmethod
    def _mapped_identities_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("mapped identities must be unique")
        for value in values:
            if re.fullmatch(_ID_PATTERN, value) is None:
                raise ValueError("mapped identities must be bounded")
        return values

    @field_validator("evidence_references")
    @classmethod
    def _evidence_references_are_bounded_and_unique(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate evidence reference on local disposition")
        for value in values:
            if not value.strip():
                raise ValueError("evidence references must be non-empty")
            reason = reference_rejection_reason(value)
            if reason is not None:
                raise ValueError(reason)
        return values

    @field_validator("reason", "limitation")
    @classmethod
    def _text_is_one_safe_line(cls, value: str) -> str:
        if _CONTROL.search(value):
            raise ValueError("a local disposition explanation must be one bounded line")
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
            raise ValueError("a scored local disposition requires evidence")
        return self

    @property
    def status(self) -> OperationalState:
        """Compatibility alias for consumers that call operational state status."""

        return self.operational_state

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        """Compatibility alias for evidence references on a local row."""

        return self.evidence_references

    @property
    def catalogue_ids(self) -> tuple[str, ...]:
        """Compatibility alias for mapped Dex identities."""

        return self.mapped_catalogue_ids

    @property
    def capability_ids(self) -> tuple[str, ...]:
        """Compatibility alias for mapped human capability identities."""

        return self.mapped_capability_ids


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
    local_entries: tuple[LocalObservationDisposition, ...] = ()
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
        observation_ids = [item.observation_id for item in self.local_entries]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("comparison ledger contains a duplicate observation identity")
        capability_ids = [item.capability_id for item in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("comparison ledger contains a duplicate human capability identity")
        return self

    @classmethod
    def for_catalogue(
        cls,
        catalogue: CatalogueV2,
        *,
        fingerprint: EvidenceFingerprint | None = None,
        catalogue_version: int,
        catalogue_sha256: str,
        capabilities: tuple[HumanCapability, ...],
        entries: tuple[CatalogueDisposition, ...],
        local_entries: tuple[LocalObservationDisposition, ...] | None = None,
        reciprocal_answer: str = _NO_TRANSFERABLE_METHOD,
    ) -> ComparisonLedger:
        """Validate a ledger against the exact verified catalogue identity set.

        ``for_catalogue`` remains a small compatibility wrapper for family-free
        tests and old stored fixtures.  New production code must pass a
        fingerprint, which routes to :meth:`for_catalogue_and_fingerprint`.
        """

        if fingerprint is not None:
            return cls.for_catalogue_and_fingerprint(
                catalogue,
                fingerprint=fingerprint,
                catalogue_version=catalogue_version,
                catalogue_sha256=catalogue_sha256,
                capabilities=capabilities,
                entries=entries,
                local_entries=local_entries,
                reciprocal_answer=reciprocal_answer,
            )
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
            local_entries=local_entries or (),
            reciprocal_answer=reciprocal_answer,
        )

    @classmethod
    def for_catalogue_and_fingerprint(
        cls,
        catalogue: CatalogueV2,
        *,
        fingerprint: EvidenceFingerprint,
        catalogue_version: int,
        catalogue_sha256: str,
        capabilities: tuple[HumanCapability, ...],
        entries: tuple[CatalogueDisposition, ...],
        local_entries: tuple[LocalObservationDisposition, ...] | None = None,
        reciprocal_answer: str = _NO_TRANSFERABLE_METHOD,
    ) -> ComparisonLedger:
        """Construct a complete, bidirectional ledger from verified inputs."""

        # Reuse the compatibility path for the catalogue side so all existing
        # recommendation and human-capability checks remain in one place.
        base = cls.for_catalogue(
            catalogue,
            catalogue_version=catalogue_version,
            catalogue_sha256=catalogue_sha256,
            capabilities=capabilities,
            entries=entries,
            reciprocal_answer=reciprocal_answer,
        )
        expected_observation_ids = tuple(
            observation_id_for(item) for item in fingerprint.observations
        )
        supplied = (
            tuple(local_entries)
            if local_entries is not None
            else _seed_local_entries(fingerprint)
        )
        actual_observation_ids = tuple(item.observation_id for item in supplied)
        if (
            len(actual_observation_ids) != len(set(actual_observation_ids))
            or set(actual_observation_ids) != set(expected_observation_ids)
        ):
            raise _model_validation_error(
                "local ledger entries must equal the fingerprint observation identity set",
                actual_observation_ids,
            )
        expected_by_id = {
            observation_id_for(item): item for item in fingerprint.observations
        }
        for entry in supplied:
            observation = expected_by_id[entry.observation_id]
            if (
                entry.kind is not observation.kind
                or entry.identity != observation.identity
                or entry.operational_state is not observation.operational_state
            ):
                raise _model_validation_error(
                    "local ledger observation facts must match the fingerprint",
                    entry.observation_id,
                )
            known_catalogue_ids = {base_entry.catalogue_id for base_entry in base.entries}
            if any(item not in known_catalogue_ids for item in entry.mapped_catalogue_ids):
                raise _model_validation_error(
                    "local ledger maps an unknown catalogue identity",
                    entry.mapped_catalogue_ids,
                )
            known_capability_ids = {
                capability.capability_id for capability in base.capabilities
            }
            if any(item not in known_capability_ids for item in entry.mapped_capability_ids):
                raise _model_validation_error(
                    "local ledger maps an unknown capability identity",
                    entry.mapped_capability_ids,
                )
        known_observations = set(expected_observation_ids)
        unknown_person_observations = sorted(
            {
                observation_id
                for capability in base.capabilities
                for observation_id in capability.person_observation_ids
                if observation_id not in known_observations
            }
        )
        if unknown_person_observations:
            raise _model_validation_error(
                "human capabilities reference unknown observation IDs",
                unknown_person_observations,
            )
        return cls(
            catalogue_version=base.catalogue_version,
            catalogue_sha256=base.catalogue_sha256,
            capabilities=base.capabilities,
            entries=base.entries,
            local_entries=supplied,
            reciprocal_answer=base.reciprocal_answer,
        )

    def derived_summary(self) -> LedgerSummary:
        """Return coverage counts calculated from this ledger's entries."""

        from capability_exchange.diagnosis.report import LedgerSummary

        return LedgerSummary.from_ledger(self)


def _seed_local_entries(
    fingerprint: EvidenceFingerprint,
) -> tuple[LocalObservationDisposition, ...]:
    """Seed every captured observation with an honest not-assessed answer."""

    return tuple(
        LocalObservationDisposition(
            observation_id=observation_id_for(observation),
            kind=observation.kind,
            identity=observation.identity,
            operational_state=observation.operational_state,
            disposition=Disposition.NOT_ASSESSED,
            evidence_references=(observation.evidence.reference,),
            reason=_NO_LOCAL_PROPOSAL,
            limitation=_NO_LOCAL_PROPOSAL,
        )
        for observation in fingerprint.observations
    )
