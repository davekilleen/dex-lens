"""Complete, evidence-led two-way comparison with a verified catalogue."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.catalogue.v2 import (
    CapabilityReferenceV2,
    CatalogueV2,
    McpServerCapabilityEntryV2,
    McpToolReferenceV2,
    NangoProviderReferenceV2,
    SourceComponentReferenceV2,
    capability_availability_of,
)
from capability_exchange.diagnosis.families import (
    FamilyAvailability,
    FamilyDelta,
    build_family_delta,
    summarise_family,
)
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    EvidenceFingerprint,
    HealthState,
    ObservationKind,
    OperationalState,
    RuntimeState,
    observation_id_for,
    upgrade_stored_observation_payload,
)
from capability_exchange.diagnosis.significant_families import (
    ComponentMatchBasis,
    FamilyAssessmentDisposition,
    SignificantFamilyAssessment,
    assess_significant_families,
)
from capability_exchange.evidence.item import reference_rejection_reason

__all__ = [
    "CatalogueDisposition",
    "ComparisonLedger",
    "Disposition",
    "FamilyComponentEvidence",
    "FamilyLedgerEntry",
    "HumanCapability",
    "LocalObservationDisposition",
    "McpToolInventory",
    "VersionDistance",
    "family_entries_from_assessments",
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
        if self.disposition is Disposition.DEX_SHOULD_LEARN and not self.method_compared:
            raise ValueError("Dex-should-learn requires method evidence, not identity overlap")
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


class McpToolInventory(InventoriedModel):
    """One signed MCP inventory, complete or honestly marked as sampled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    server_id: str = Field(pattern=_ID_PATTERN)
    server_name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,80}$")
    inventory_status: Literal["sampled", "complete"]
    declared_tool_count: int = Field(ge=1, le=500)
    tools: tuple[str, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_complete_rows(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        upgraded = dict(value)
        tools = upgraded.get("tools")
        if isinstance(tools, (list, tuple)):
            upgraded.setdefault("inventory_status", "complete")
            upgraded.setdefault("declared_tool_count", len(tools))
        return upgraded

    @field_validator("tools")
    @classmethod
    def _tools_are_bounded_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("MCP tool inventory must not contain duplicates")
        if any(re.fullmatch(r"^[a-z][a-z0-9_]{0,119}$", value) is None for value in values):
            raise ValueError("MCP tool inventory contains an invalid tool identity")
        return values

    @model_validator(mode="after")
    def _inventory_scope_is_honest(self) -> Self:
        if self.inventory_status == "complete" and self.declared_tool_count != len(self.tools):
            raise ValueError("complete MCP inventory must contain every declared tool")
        if self.inventory_status == "sampled" and self.declared_tool_count < len(self.tools):
            raise ValueError("sampled MCP inventory cannot show more tools than declared")
        return self


class VersionDistance(InventoriedModel):
    """Signed skill-lineage changes after one proven local Dex release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    inspected_version: str = Field(
        pattern=r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
    )
    current_version: str = Field(
        pattern=r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
    )
    evidence_references: tuple[str, ...] = Field(min_length=1, max_length=8)
    families: tuple[FamilyDelta, ...] = Field(min_length=1, max_length=80)

    @field_validator("evidence_references")
    @classmethod
    def _evidence_is_safe_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("version-distance evidence references must be unique")
        for value in values:
            reason = reference_rejection_reason(value)
            if reason is not None:
                raise ValueError(reason)
        return values

    @model_validator(mode="after")
    def _family_rows_share_the_same_version_pair(self) -> Self:
        family_ids = [item.family_id for item in self.families]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("version distance contains a duplicate family identity")
        if any(
            item.inspected_version != self.inspected_version
            or item.current_version != self.current_version
            for item in self.families
        ):
            raise ValueError("version-distance family rows must share the proven version pair")
        return self


class FamilyComponentEvidence(InventoriedModel):
    """Exact local evidence matched to one signed family component."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_reference: str = Field(min_length=1, max_length=280)
    observation_ids: tuple[str, ...]
    evidence_references: tuple[str, ...]
    match_bases: tuple[ComponentMatchBasis, ...]
    method_equivalent: Literal[False] = False

    @field_validator("observation_ids")
    @classmethod
    def _observation_ids_are_exact_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("family component observations must be non-empty and unique")
        if any(re.fullmatch(_OBSERVATION_ID_PATTERN, value) is None for value in values):
            raise ValueError("family component contains an invalid observation identity")
        return values

    @field_validator("evidence_references")
    @classmethod
    def _component_references_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("family component evidence references must be non-empty and unique")
        for value in values:
            reason = reference_rejection_reason(value)
            if reason is not None:
                raise ValueError(reason)
        return values

    @field_validator("match_bases")
    @classmethod
    def _match_bases_are_nonempty_and_unique(
        cls, values: tuple[ComponentMatchBasis, ...]
    ) -> tuple[ComponentMatchBasis, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("family component match bases must be non-empty and unique")
        return values


class FamilyLedgerEntry(InventoriedModel):
    """One exact, evidence-bound durable row for a signed capability family."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    family_id: str = Field(pattern=_ID_PATTERN)
    title: str = Field(min_length=1, max_length=160)
    outcome: str = Field(min_length=1, max_length=800)
    signed_availability: FamilyAvailability
    available_member_ids: tuple[str, ...]
    unavailable_member_ids: tuple[str, ...]
    recommendable_member_ids: tuple[str, ...]
    matched_components: tuple[FamilyComponentEvidence, ...]
    matched_observation_ids: tuple[str, ...]
    unresolved_components: tuple[str, ...]
    evidence_references: tuple[str, ...]
    disposition: FamilyAssessmentDisposition
    reason: str = Field(min_length=1, max_length=600)

    @field_validator(
        "available_member_ids",
        "unavailable_member_ids",
        "recommendable_member_ids",
    )
    @classmethod
    def _member_ids_are_unique_and_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("family member identity lists must be unique")
        if any(re.fullmatch(_ID_PATTERN, value) is None for value in values):
            raise ValueError("family member identity must be bounded")
        return values

    @field_validator("matched_observation_ids")
    @classmethod
    def _matched_observations_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("matched family observation identities must be unique")
        if any(re.fullmatch(_OBSERVATION_ID_PATTERN, value) is None for value in values):
            raise ValueError("matched family observation identity is invalid")
        return values

    @field_validator("unresolved_components")
    @classmethod
    def _unresolved_components_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(not value for value in values):
            raise ValueError("unresolved family components must be non-empty and unique")
        return values

    @field_validator("evidence_references")
    @classmethod
    def _family_evidence_is_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("family evidence references must be unique")
        for value in values:
            reason = reference_rejection_reason(value)
            if reason is not None:
                raise ValueError(reason)
        return values

    @field_validator("reason", "title", "outcome")
    @classmethod
    def _family_text_is_safe(cls, value: str) -> str:
        if _CONTROL.search(value):
            raise ValueError("family ledger text must be bounded single-line text")
        return value

    @model_validator(mode="after")
    def _aggregate_evidence_is_exact(self) -> Self:
        component_references = [item.component_reference for item in self.matched_components]
        if len(component_references) != len(set(component_references)):
            raise ValueError("family ledger contains a duplicate matched component")
        if set(component_references) & set(self.unresolved_components):
            raise ValueError("a family component cannot be both matched and unresolved")
        observation_ids = tuple(
            sorted(
                {
                    observation_id
                    for component in self.matched_components
                    for observation_id in component.observation_ids
                }
            )
        )
        evidence_references = tuple(
            sorted(
                {
                    reference
                    for component in self.matched_components
                    for reference in component.evidence_references
                }
            )
        )
        if self.matched_observation_ids != observation_ids:
            raise ValueError("family matched observation summary must equal its component rows")
        if self.evidence_references != evidence_references:
            raise ValueError("family evidence summary must equal its component rows")
        return self


class LocalObservationDisposition(InventoriedModel):
    """One explicit, source-bound disposition for a local observation.

    The observation identity and operational facts are copied from the
    captured fingerprint.  Specialist mappings may add catalogue/capability
    identities, but cannot rewrite the source-bound observation itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def __init__(self, **data: object) -> None:
        """Accept one legacy scalar at construction, but never persist it."""

        super().__init__(**upgrade_stored_observation_payload(data))

    observation_id: str = Field(pattern=_OBSERVATION_ID_PATTERN)
    kind: ObservationKind
    identity: str = Field(pattern=_ID_PATTERN)
    configuration_state: ConfigurationState
    runtime_state: RuntimeState
    health_state: HealthState
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
    def operational_state(self) -> OperationalState:
        """Project the exact axes for old in-memory readers; never serialize it."""

        runtime = {
            RuntimeState.LOADED: OperationalState.LOADED,
            RuntimeState.RECENTLY_RUN: OperationalState.RECENTLY_RUN,
            RuntimeState.OUTCOME_VERIFIED: OperationalState.OUTCOME_VERIFIED,
            RuntimeState.STALE: OperationalState.STALE,
            RuntimeState.DISABLED: OperationalState.DISABLED,
            RuntimeState.CONFLICTING: OperationalState.CONFLICTING,
            RuntimeState.ABSENT: OperationalState.ABSENT,
            RuntimeState.UNSUPPORTED: OperationalState.UNSUPPORTED,
        }.get(self.runtime_state)
        if runtime is not None:
            return runtime
        try:
            return OperationalState(self.configuration_state.value)
        except ValueError:
            return OperationalState.NOT_ASSESSED

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


def _signed_component_reference(component: object) -> str:
    if isinstance(component, CapabilityReferenceV2):
        return f"capability:{component.capability_id}"
    if isinstance(component, McpToolReferenceV2):
        return f"mcp-tool:{component.server_id}:{component.tool_name}"
    if isinstance(component, NangoProviderReferenceV2):
        return f"nango-provider:{component.provider_id}"
    if isinstance(component, SourceComponentReferenceV2):
        return f"source-component:{component.component_id}"
    raise TypeError("family component must be a validated signed component")


def family_entries_from_assessments(
    catalogue: CatalogueV2,
    assessments: tuple[SignificantFamilyAssessment, ...],
) -> tuple[FamilyLedgerEntry, ...]:
    """Bind deterministic assessment values to exact signed family prose."""

    family_by_id = {family.family_id: family for family in catalogue.capability_families}
    assessment_by_id = {item.family_id: item for item in assessments}
    if len(assessment_by_id) != len(assessments) or set(assessment_by_id) != set(
        family_by_id
    ):
        raise _model_validation_error(
            "family entries must equal the verified catalogue family identity set",
            tuple(sorted(assessment_by_id)),
        )
    return tuple(
        FamilyLedgerEntry(
            family_id=assessment.family_id,
            title=family_by_id[assessment.family_id].title,
            outcome=family_by_id[assessment.family_id].outcome,
            signed_availability=assessment.signed_availability,
            available_member_ids=assessment.available_member_ids,
            unavailable_member_ids=assessment.unavailable_member_ids,
            recommendable_member_ids=assessment.recommendable_member_ids,
            matched_components=tuple(
                FamilyComponentEvidence(
                    component_reference=component.component_reference,
                    observation_ids=component.observation_ids,
                    evidence_references=component.evidence_references,
                    match_bases=component.match_bases,
                    method_equivalent=component.method_equivalent,
                )
                for component in assessment.matched_components
            ),
            matched_observation_ids=assessment.matched_observation_ids,
            unresolved_components=assessment.unresolved_components,
            evidence_references=assessment.evidence_references,
            disposition=assessment.disposition,
            reason=assessment.reason,
        )
        for assessment in sorted(assessments, key=lambda item: item.family_id)
    )


def _validate_family_entries(
    catalogue: CatalogueV2,
    family_entries: tuple[FamilyLedgerEntry, ...],
) -> tuple[FamilyLedgerEntry, ...]:
    expected_by_id = {
        family.family_id: family
        for family in sorted(catalogue.capability_families, key=lambda item: item.family_id)
    }
    actual_by_id = {entry.family_id: entry for entry in family_entries}
    if len(actual_by_id) != len(family_entries) or set(actual_by_id) != set(expected_by_id):
        raise _model_validation_error(
            "family entries must equal the verified catalogue family identity set",
            tuple(sorted(actual_by_id)),
        )
    capabilities = {entry.capability_id: entry for entry in catalogue.capabilities}
    for family_id, family in expected_by_id.items():
        entry = actual_by_id[family_id]
        summary = summarise_family(
            family,
            tuple(capabilities[member_id] for member_id in family.member_capability_ids),
        )
        exact_signed_truth = (
            entry.title == family.title
            and entry.outcome == family.outcome
            and entry.signed_availability is summary.availability
            and entry.available_member_ids == summary.available_member_ids
            and entry.unavailable_member_ids == summary.unavailable_member_ids
            and entry.recommendable_member_ids == summary.recommendable_member_ids
        )
        expected_components = tuple(
            sorted(_signed_component_reference(component) for component in family.components)
        )
        actual_components = tuple(
            sorted(
                [
                    *(component.component_reference for component in entry.matched_components),
                    *entry.unresolved_components,
                ]
            )
        )
        if not exact_signed_truth or actual_components != expected_components:
            raise _model_validation_error(
                "family entry must preserve exact signed family truth",
                family_id,
            )
    return tuple(actual_by_id[family_id] for family_id in sorted(expected_by_id))


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
    mcp_tools_by_server: tuple[McpToolInventory, ...] = ()
    family_entries: tuple[FamilyLedgerEntry, ...] = ()
    version_distance: VersionDistance | None = None
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
        server_ids = [item.server_id for item in self.mcp_tools_by_server]
        server_names = [item.server_name for item in self.mcp_tools_by_server]
        if len(server_ids) != len(set(server_ids)) or len(server_names) != len(set(server_names)):
            raise ValueError("comparison ledger contains a duplicate MCP server tool inventory")
        family_ids = [item.family_id for item in self.family_entries]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("comparison ledger contains a duplicate family identity")
        if self.version_distance is not None:
            delta_by_id = {item.family_id: item for item in self.version_distance.families}
            family_by_id = {item.family_id: item for item in self.family_entries}
            if not set(delta_by_id) <= set(family_by_id):
                raise ValueError("version distance references an unknown signed family")
            for family_id, delta in delta_by_id.items():
                family = family_by_id[family_id]
                if (
                    delta.title != family.title
                    or delta.outcome != family.outcome
                    or delta.availability is not family.signed_availability
                    or delta.available_member_ids != family.available_member_ids
                    or delta.unavailable_member_ids != family.unavailable_member_ids
                    or delta.recommendable_member_ids != family.recommendable_member_ids
                ):
                    raise ValueError("version distance must preserve exact signed family truth")
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
        mcp_tools_by_server: tuple[McpToolInventory, ...] | None = None,
        family_entries: tuple[FamilyLedgerEntry, ...] | None = None,
        version_distance: VersionDistance | None = None,
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
                mcp_tools_by_server=mcp_tools_by_server,
                family_entries=family_entries,
                version_distance=version_distance,
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
        unavailable_recommendations = sorted(
            entry.catalogue_id
            for entry in entries
            if entry.disposition is Disposition.WORTH_BORROWING
            and capability_availability_of(
                next(
                    item
                    for item in catalogue.capabilities
                    if item.capability_id == entry.catalogue_id
                )
            )
            != "active"
        )
        if unavailable_recommendations:
            raise _model_validation_error(
                "unavailable catalogue entries cannot be recommended: "
                + ", ".join(unavailable_recommendations),
                unavailable_recommendations,
            )
        exact_mcp_tools = _mcp_tool_inventory(catalogue)
        if mcp_tools_by_server is not None and tuple(mcp_tools_by_server) != exact_mcp_tools:
            raise _model_validation_error(
                "ledger MCP tool inventory must equal the exact verified catalogue inventory",
                mcp_tools_by_server,
            )
        exact_family_entries = _validate_family_entries(catalogue, family_entries or ())
        if version_distance is not None:
            entries_by_id = {item.capability_id: item for item in catalogue.capabilities}
            expected_deltas = tuple(
                delta
                for family in sorted(catalogue.capability_families, key=lambda item: item.family_id)
                if (
                    delta := build_family_delta(
                        current_version=version_distance.current_version,
                        inspected_version=version_distance.inspected_version,
                        family=family,
                        entries=tuple(
                            entries_by_id[member_id]
                            for member_id in family.member_capability_ids
                        ),
                    )
                )
                is not None
            )
            if version_distance.families != expected_deltas:
                raise _model_validation_error(
                    "version distance must equal exact signed release lineage",
                    version_distance.families,
                )
        return cls(
            catalogue_version=catalogue_version,
            catalogue_sha256=catalogue_sha256,
            capabilities=capabilities,
            entries=entries,
            mcp_tools_by_server=exact_mcp_tools,
            family_entries=exact_family_entries,
            version_distance=version_distance,
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
        mcp_tools_by_server: tuple[McpToolInventory, ...] | None = None,
        family_entries: tuple[FamilyLedgerEntry, ...] | None = None,
        version_distance: VersionDistance | None = None,
        local_entries: tuple[LocalObservationDisposition, ...] | None = None,
        reciprocal_answer: str = _NO_TRANSFERABLE_METHOD,
    ) -> ComparisonLedger:
        """Construct a complete, bidirectional ledger from verified inputs."""

        assessed_family_entries = family_entries_from_assessments(
            catalogue,
            assess_significant_families(catalogue, fingerprint),
        )
        if family_entries is not None and tuple(family_entries) != assessed_family_entries:
            raise _model_validation_error(
                "family entries must equal the deterministic fingerprint assessment",
                family_entries,
            )

        # Reuse the compatibility path for the catalogue side so all existing
        # recommendation and human-capability checks remain in one place.
        base = cls.for_catalogue(
            catalogue,
            catalogue_version=catalogue_version,
            catalogue_sha256=catalogue_sha256,
            capabilities=capabilities,
            entries=entries,
            mcp_tools_by_server=mcp_tools_by_server,
            family_entries=assessed_family_entries,
            version_distance=version_distance,
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
                or entry.configuration_state is not observation.configuration_state
                or entry.runtime_state is not observation.runtime_state
                or entry.health_state is not observation.health_state
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
            mcp_tools_by_server=base.mcp_tools_by_server,
            family_entries=base.family_entries,
            version_distance=base.version_distance,
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
            configuration_state=observation.configuration_state,
            runtime_state=observation.runtime_state,
            health_state=observation.health_state,
            disposition=Disposition.NOT_ASSESSED,
            evidence_references=(observation.evidence.reference,),
            reason=_NO_LOCAL_PROPOSAL,
            limitation=_NO_LOCAL_PROPOSAL,
        )
        for observation in fingerprint.observations
    )


def _mcp_tool_inventory(catalogue: CatalogueV2) -> tuple[McpToolInventory, ...]:
    """Copy every signed MCP inventory and preserve whether it is sampled."""

    return tuple(
        McpToolInventory(
            server_id=entry.capability_id,
            server_name=entry.server_name,
            inventory_status=entry.tool_inventory,
            declared_tool_count=entry.tool_count,
            tools=(entry.tools if entry.tool_inventory == "complete" else entry.example_tools),
        )
        for entry in sorted(catalogue.capabilities, key=lambda item: item.capability_id)
        if isinstance(entry, McpServerCapabilityEntryV2)
    )
