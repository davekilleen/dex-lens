"""Dex Lens signed Capability Catalog v2 contract.

The catalogue is public Dex product data, fetched only after consent and then
verified locally. Verification fails closed: unsigned, tampered, unknown-key,
malformed, expired, or rollback catalogues produce no usable catalogue.
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import (
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.foundations import FoundationCapability

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CatalogueId = Annotated[str, Field(pattern=_ID_RE.pattern)]
_SemanticVersion = Annotated[str, Field(pattern=_SEMVER_RE.pattern)]
_ToolName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
_ProviderId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,80}$")]

# The four kinds of capability a Dex release can publish, the publisher's
# reviewed impact ranking, and whether the capability is currently offered.
# All three are closed: an unknown class, tier, or availability is a schema
# failure, never a guess.
CapabilityClassV2 = Literal[
    "active-skill",
    "mcp-server",
    "scheduled-automation",
    "system-engine",
]
ImpactTierV2 = Literal["core", "high", "medium", "niche"]
CapabilityAvailabilityV2 = Literal["active", "dormant", "parked"]

# Family assessments are deliberately declarative.  A profile names one of
# Lens's reviewed, read-only detector families; it is not a command, module
# path, or executable snippet supplied by a catalogue producer.
AssessmentProfileV2 = Literal[
    "catalogue",
    "mcp",
    "mcp-tool",
    "filesystem",
    "source-component",
    "provider",
    "scheduled-automation",
    "health",
    "doctor",
]

# A repository-relative path published as public product metadata: never
# absolute, never traversing upward. Lens only displays these; the pattern
# keeps a signed catalogue from smuggling an absolute or escaping path into
# text a person may paste somewhere it resolves.
SAFE_RELATIVE_PATH_PATTERN = r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$)).+"
_SafeRelativePath = Annotated[
    str, Field(min_length=1, max_length=512, pattern=SAFE_RELATIVE_PATH_PATTERN)
]
_FoundationCapabilityId = Literal[
    "ownership-portability",
    "privacy-minimal-disclosure",
    "context-orientation",
    "durable-memory-provenance",
    "scoped-agency-human-control",
    "safe-change-recovery",
    "honest-health-observability",
    "compounding-correctability",
]
_CONTRACT_VERSION = "dex-lens-catalogue-v2"
_CACHE_FILE = "lens-catalogue-v2-cache.json"
UNIQUE_BY_KEYWORD = "x-dex-lens-unique-by"
UNIQUE_COMPONENT_IDENTITY_KEYWORD = "x-dex-lens-unique-component-identity"

# Release-owned Dex Core signing keys. Private keys live only in the Dex release
# environment; Lens ships public keys so catalogues verify locally.
PINNED_PUBLIC_KEYS_BY_KEY_ID: dict[str, str] = {
    "dex-core-lens-1": "+0CGlXczAUI8FKeEi0ekfRb1ajc/mFsm2xM17hOU1+o=",
}


class CatalogueVerificationError(Exception):
    """A Capability Catalog could not be verified. No catalogue is usable."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogueVerificationError(f"{label} must be a JSON object")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def canonical_signed_payload(envelope: dict[str, Any]) -> bytes:
    """Canonical bytes covered by the catalogue signature.

    The signature covers exactly ``metadata`` and ``catalogue``. The
    ``signature`` field is excluded so the same canonical payload is used by
    the producer and the Lens verifier.
    """
    return _canonical_json_bytes(
        {
            "metadata": envelope.get("metadata"),
            "catalogue": envelope.get("catalogue"),
        }
    )


@dataclass(frozen=True)
class KeyRing:
    """Pinned Dex Core public keys, indexed by ``key_id``."""

    public_keys_b64: dict[str, str]

    def public_key(self, key_id: str) -> Ed25519PublicKey:
        encoded = self.public_keys_b64.get(key_id)
        if encoded is None:
            raise CatalogueVerificationError(f"unknown catalogue signing key_id {key_id!r}")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise CatalogueVerificationError(f"pinned public key {key_id!r} is not base64") from exc
        if len(raw) != 32:
            raise CatalogueVerificationError(f"pinned public key {key_id!r} is not Ed25519 raw")
        return Ed25519PublicKey.from_public_bytes(raw)


def default_keyring() -> KeyRing:
    """The Lens-shipped pinned Dex Core public-key table."""
    return KeyRing(PINNED_PUBLIC_KEYS_BY_KEY_ID)


class CatalogueMetadataV2(InventoriedModel):
    contract_version: Literal["dex-lens-catalogue-v2"]
    catalog_version: int = Field(ge=1)
    produced_at: datetime
    expires_at: datetime
    producer: str = Field(min_length=1, max_length=120)
    core_release: str = Field(min_length=1, max_length=120)
    key_id: str = Field(min_length=1, max_length=120)

    @field_validator("produced_at", "expires_at")
    @classmethod
    def _timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("catalogue timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _expires_after_produced(self) -> CatalogueMetadataV2:
        if self.expires_at <= self.produced_at:
            raise ValueError("catalogue expires_at must be after produced_at")
        return self


class JobTaxonomyEntryV2(InventoriedModel):
    job_id: str = Field(pattern=_ID_RE.pattern)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=600)
    confirmed_gap_signals: tuple[str, ...] = Field(min_length=1, max_length=12)


class CapabilityEvidenceV2(InventoriedModel):
    level: Literal["verified", "supported", "reported", "unknown"]
    source: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    limitations: str = Field(min_length=1, max_length=1000)


class CapabilityCompatibilityV2(InventoriedModel):
    host_adapters: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    foundation_capabilities: tuple[_FoundationCapabilityId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    minimum_lens_contract: str = Field(pattern=_SEMVER_RE.pattern)
    platforms: tuple[Literal["macos", "linux", "windows"], ...] = Field(
        min_length=1, max_length=3
    )
    needs_hooks: bool
    needs_mcp: bool
    host_requirements: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    limitations: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("host_adapters", "foundation_capabilities")
    @classmethod
    def _ids_are_kebab_case(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not _ID_RE.match(value):
                raise ValueError(f"{value!r} is not a catalogue id")
        if len(set(values)) != len(values):
            raise ValueError("duplicate compatibility id")
        return values

    @field_validator("foundation_capabilities")
    @classmethod
    def _foundation_capabilities_are_known(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        known = {capability.value for capability in FoundationCapability}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"unknown foundation capability id: {', '.join(unknown)}")
        return values

    @field_validator("host_requirements")
    @classmethod
    def _host_requirements_are_kebab_case(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not _ID_RE.match(value):
                raise ValueError(f"{value!r} is not a host requirement id")
        if len(set(values)) != len(values):
            raise ValueError("duplicate host requirement id")
        return values


class CapabilityPortableBriefV2(InventoriedModel):
    goal: str = Field(min_length=1, max_length=200)
    method_outline: tuple[str, ...] = Field(min_length=1, max_length=20)
    verification_checklist: tuple[str, ...] = Field(min_length=1, max_length=20)
    rollback_advice: str = Field(min_length=1, max_length=1000)
    safety_notes: tuple[str, ...] = Field(min_length=1, max_length=20)


def _job_ids_are_unique_catalogue_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError("duplicate job id on capability entry")
    for value in values:
        if not _ID_RE.match(value):
            raise ValueError(f"{value!r} is not a catalogue job id")
    return values


def _changed_versions_are_unique_semver(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError("duplicate changed_in version")
    for value in values:
        if not _SEMVER_RE.match(value):
            raise ValueError(f"{value!r} is not a semantic version")
    return values


def _paths_are_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError("duplicate path on capability entry")
    return values


class LegacySkillCapabilityEntryV2(InventoriedModel):
    """A skill entry exactly as every already-signed catalogue publishes it.

    This is the transition branch of the 0.1.9 contract: the currently
    published catalogue is skill-only and its entries carry none of the
    class fields, so this model stays byte-for-byte what those signed
    catalogues were validated against. It is closed and skill-shaped —
    every skill field is required and unknown fields are rejected — so a
    classless non-skill entry cannot slip in through it. Removing this
    branch is a later, explicit compatibility decision once every supported
    Core catalogue carries the enriched fields.
    """

    capability_id: str = Field(pattern=_ID_RE.pattern)
    title: str = Field(min_length=1, max_length=140)
    summary: str = Field(min_length=1, max_length=1200)
    value: str = Field(min_length=1, max_length=1200)
    jobs: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    prerequisites: tuple[str, ...] = Field(min_length=1, max_length=20)
    trade_offs: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence: tuple[CapabilityEvidenceV2, ...] = Field(min_length=1, max_length=20)
    compatibility: CapabilityCompatibilityV2
    docs_url: str = Field(min_length=1, max_length=300)
    since_release: str = Field(pattern=_SEMVER_RE.pattern)
    changed_in: tuple[_SemanticVersion, ...] = Field(
        max_length=40, json_schema_extra={"uniqueItems": True}
    )
    release_provenance: Literal["core-release"]
    portable_brief: CapabilityPortableBriefV2

    _jobs_unique = field_validator("jobs")(_job_ids_are_unique_catalogue_ids)
    _changed_in_semver = field_validator("changed_in")(_changed_versions_are_unique_semver)


class ActiveSkillCapabilityEntryV2(InventoriedModel):
    """An enriched skill entry: the legacy skill shape plus the class fields.

    A skill keeps every legacy field — compatibility, docs_url,
    since_release, changed_in and the portable rebuild brief are skill-only
    and stay required here, and only here. A dormant skill still validates;
    consumers must never offer it as an active recommendation.
    """

    capability_class: Literal["active-skill"]
    impact_tier: ImpactTierV2
    availability: Literal["active", "dormant"]
    capability_id: str = Field(pattern=_ID_RE.pattern)
    title: str = Field(min_length=1, max_length=140)
    summary: str = Field(min_length=1, max_length=1200)
    value: str = Field(min_length=1, max_length=1200)
    jobs: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    prerequisites: tuple[str, ...] = Field(min_length=1, max_length=20)
    trade_offs: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence: tuple[CapabilityEvidenceV2, ...] = Field(min_length=1, max_length=20)
    compatibility: CapabilityCompatibilityV2
    docs_url: str = Field(min_length=1, max_length=300)
    since_release: str = Field(pattern=_SEMVER_RE.pattern)
    changed_in: tuple[_SemanticVersion, ...] = Field(
        max_length=40, json_schema_extra={"uniqueItems": True}
    )
    release_provenance: Literal["core-release"]
    portable_brief: CapabilityPortableBriefV2

    _jobs_unique = field_validator("jobs")(_job_ids_are_unique_catalogue_ids)
    _changed_in_semver = field_validator("changed_in")(_changed_versions_are_unique_semver)


class McpServerCapabilityEntryV2(InventoriedModel):
    """An MCP server Dex runs: adopted by running Dex, never rebuilt from a page.

    The catalogue id stays kebab-case; the server's own name is preserved
    separately as ``server_name``. No skill-only field is permitted here.
    """

    # The safe-relative-path pattern uses lookaheads, which the default rust
    # regex engine cannot compile; Python's `re` can, and is what the
    # exported JSON Schema's reference validator uses too.
    model_config = ConfigDict(extra="forbid", regex_engine="python-re")

    capability_class: Literal["mcp-server"]
    impact_tier: ImpactTierV2
    availability: Literal["active"]
    capability_id: str = Field(pattern=_ID_RE.pattern)
    title: str = Field(min_length=1, max_length=140)
    summary: str = Field(min_length=1, max_length=1200)
    value: str = Field(min_length=1, max_length=1200)
    jobs: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    prerequisites: tuple[str, ...] = Field(min_length=1, max_length=20)
    trade_offs: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence: tuple[CapabilityEvidenceV2, ...] = Field(min_length=1, max_length=20)
    release_provenance: Literal["core-release"]
    server_name: str = Field(pattern=r"^dex-[a-z0-9-]+$")
    tool_count: int = Field(ge=1)
    example_tools: tuple[_ToolName, ...] = Field(
        min_length=1, max_length=5, json_schema_extra={"uniqueItems": True}
    )
    # Existing v6 catalogues only publish a count and a few examples.  The
    # fields below are additive so those sampled entries continue to verify;
    # a complete inventory opts in explicitly and is checked against the
    # exact tool tuple.
    tools: tuple[_ToolName, ...] = Field(
        default=(), max_length=500, json_schema_extra={"uniqueItems": True}
    )
    tool_inventory: Literal["sampled", "complete"] = "sampled"
    source_paths: tuple[_SafeRelativePath, ...] = Field(
        min_length=1, max_length=300, json_schema_extra={"uniqueItems": True}
    )

    _jobs_unique = field_validator("jobs")(_job_ids_are_unique_catalogue_ids)
    _paths_unique = field_validator("source_paths")(_paths_are_unique)

    @field_validator("example_tools")
    @classmethod
    def _example_tools_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("duplicate example tool on capability entry")
        return values

    @field_validator("tools")
    @classmethod
    def _tools_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("duplicate tool on capability entry")
        return values

    @model_validator(mode="after")
    def _complete_inventory_is_exact(self) -> McpServerCapabilityEntryV2:
        if self.tool_inventory != "complete":
            return self
        if not self.tools:
            raise ValueError("complete MCP tool inventory must be non-empty")
        if self.tool_count != len(self.tools):
            raise ValueError(
                "complete MCP tool inventory tool_count must equal the number of tools "
                f"({self.tool_count} != {len(self.tools)})"
            )
        missing_examples = sorted(set(self.example_tools) - set(self.tools))
        if missing_examples:
            raise ValueError(
                "complete MCP tool inventory examples must be a subset of tools: "
                + ", ".join(missing_examples)
            )
        return self


class CapabilityReferenceV2(InventoriedModel):
    """A component that points to one signed catalogue capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_type: Literal["capability"]
    capability_id: _CatalogueId


class McpToolReferenceV2(InventoriedModel):
    """A component that names one exact tool on one MCP server."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_type: Literal["mcp-tool"]
    server_id: _CatalogueId
    tool_name: _ToolName


class NangoProviderReferenceV2(InventoriedModel):
    """A safe provider *type* identity from the pinned Nango data package."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_type: Literal["nango-provider"]
    provider_id: _ProviderId
    source_package: Literal["@nangohq/providers"]
    source_version: _SemanticVersion
    # Support and security review are intentionally separate dimensions.  A
    # provider may be known to Dex but not yet security-reviewed (or vice
    # versa); no single status field can smuggle one claim into the other.
    dex_support: Literal["supported", "unsupported"]
    security_vetted: bool


class SourceComponentReferenceV2(InventoriedModel):
    """A reviewed Lens-side source component identity (never a path)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_type: Literal["source-component"]
    component_id: _CatalogueId


CapabilityComponentV2 = Annotated[
    CapabilityReferenceV2
    | McpToolReferenceV2
    | NangoProviderReferenceV2
    | SourceComponentReferenceV2,
    Field(discriminator="component_type"),
]

# Short aliases keep the public contract ergonomic for producers and tests
# while the longer class names make the generated schema self-explanatory.
CapabilityRefV2 = CapabilityReferenceV2
McpToolRefV2 = McpToolReferenceV2
NangoProviderRefV2 = NangoProviderReferenceV2
SourceComponentRefV2 = SourceComponentReferenceV2


class AutomaticAssessmentV2(InventoriedModel):
    """A closed reference to one built-in read-only detector profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["automatic"]
    profile: AssessmentProfileV2


class ManualOnlyAssessmentV2(InventoriedModel):
    """A family that intentionally needs a human review rather than a detector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["manual-only"]
    reason: str = Field(min_length=1, max_length=600)

    @field_validator("reason")
    @classmethod
    def _reason_is_safe_text(cls, value: str) -> str:
        if _CONTROL_RE.search(value):
            raise ValueError("manual-only reason must be one bounded line")
        return value


CapabilityAssessmentV2 = Annotated[
    AutomaticAssessmentV2 | ManualOnlyAssessmentV2,
    Field(discriminator="mode"),
]

# Public short aliases for callers that use the contract vocabulary directly.
AutomaticAssessment = AutomaticAssessmentV2
ManualOnlyAssessment = ManualOnlyAssessmentV2


class ScheduledAutomationCapabilityEntryV2(InventoriedModel):
    """A scheduled automation Dex installs (e.g. a launchd job).

    The catalogue id stays kebab-case (``dex-meeting-intel``); the literal
    launchd label is preserved separately as ``automation_label``
    (``com.dex.meeting-intel``). No skill-only field is permitted here.
    """

    model_config = ConfigDict(extra="forbid", regex_engine="python-re")

    capability_class: Literal["scheduled-automation"]
    impact_tier: ImpactTierV2
    availability: Literal["active"]
    capability_id: str = Field(pattern=_ID_RE.pattern)
    title: str = Field(min_length=1, max_length=140)
    summary: str = Field(min_length=1, max_length=1200)
    value: str = Field(min_length=1, max_length=1200)
    jobs: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    prerequisites: tuple[str, ...] = Field(min_length=1, max_length=20)
    trade_offs: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence: tuple[CapabilityEvidenceV2, ...] = Field(min_length=1, max_length=20)
    release_provenance: Literal["core-release"]
    automation_label: str = Field(pattern=r"^com\.dex\.[a-z0-9.-]+$")
    cadence: str = Field(min_length=1, max_length=200)
    source_paths: tuple[_SafeRelativePath, ...] = Field(
        min_length=1, max_length=300, json_schema_extra={"uniqueItems": True}
    )
    installer_path: _SafeRelativePath
    # A program target may be a template that keeps its path token verbatim,
    # so it is bounded text, not a safe-relative path.
    program_target: str = Field(min_length=1, max_length=512)
    run_at_load: bool

    _jobs_unique = field_validator("jobs")(_job_ids_are_unique_catalogue_ids)
    _paths_unique = field_validator("source_paths")(_paths_are_unique)


class SystemEngineCapabilityEntryV2(InventoriedModel):
    """A multi-component engine inside Dex itself.

    ``parked`` exists for engines that ship but are not currently offered
    (e.g. ``ritual-intelligence-engine``); a parked entry validates but must
    never be ranked as an available recommendation. No skill-only field is
    permitted here.
    """

    model_config = ConfigDict(extra="forbid", regex_engine="python-re")

    capability_class: Literal["system-engine"]
    impact_tier: ImpactTierV2
    availability: Literal["active", "parked"]
    capability_id: str = Field(pattern=_ID_RE.pattern)
    title: str = Field(min_length=1, max_length=140)
    summary: str = Field(min_length=1, max_length=1200)
    value: str = Field(min_length=1, max_length=1200)
    jobs: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    prerequisites: tuple[str, ...] = Field(min_length=1, max_length=20)
    trade_offs: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence: tuple[CapabilityEvidenceV2, ...] = Field(min_length=1, max_length=20)
    release_provenance: Literal["core-release"]
    source_paths: tuple[_SafeRelativePath, ...] = Field(
        min_length=1, max_length=300, json_schema_extra={"uniqueItems": True}
    )
    component_count: int = Field(ge=1)
    example_components: tuple[_SafeRelativePath, ...] = Field(
        min_length=1, max_length=5, json_schema_extra={"uniqueItems": True}
    )

    _jobs_unique = field_validator("jobs")(_job_ids_are_unique_catalogue_ids)
    _paths_unique = field_validator("source_paths")(_paths_are_unique)
    _examples_unique = field_validator("example_components")(_paths_are_unique)

    @model_validator(mode="after")
    def _components_match_source_paths(self) -> SystemEngineCapabilityEntryV2:
        if self.component_count != len(self.source_paths):
            raise ValueError(
                "component_count must equal the number of source_paths "
                f"({self.component_count} != {len(self.source_paths)})"
            )
        missing = sorted(set(self.example_components) - set(self.source_paths))
        if missing:
            raise ValueError(
                f"example_components not present in source_paths: {', '.join(missing)}"
            )
        return self


# The enriched entry: exactly one of the four classes, chosen by the closed
# ``capability_class`` discriminator.
EnrichedCatalogueCapabilityEntryV2 = Annotated[
    ActiveSkillCapabilityEntryV2
    | McpServerCapabilityEntryV2
    | ScheduledAutomationCapabilityEntryV2
    | SystemEngineCapabilityEntryV2,
    Field(discriminator="capability_class"),
]

# The 0.1.9 rollout-compatible union: Lens must release before Core publishes
# an enriched catalogue, so this release accepts both the current signed
# skill-only catalogue (the closed legacy branch) and enriched discriminated
# entries. The class fields are never optional on the enriched branches.
CatalogueCapabilityEntryV2 = (
    LegacySkillCapabilityEntryV2 | EnrichedCatalogueCapabilityEntryV2
)


class PortableBriefContractV2(InventoriedModel):
    format: Literal["markdown"]
    audience: Literal["the person's own AI system"]
    safety_boundary: str = Field(min_length=1, max_length=400)


class CapabilityAliasV2(InventoriedModel):
    """One human-friendly alias for a canonical signed capability id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    alias: _CatalogueId
    capability_id: _CatalogueId


class CapabilityFamilyV2(InventoriedModel):
    """A signed outcome family whose state is derived from its leaf members.

    Availability is deliberately absent.  The only trustworthy status is
    calculated by :mod:`capability_exchange.diagnosis.families` from the
    member entries' existing ``capability_is_active`` result.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    family_id: _CatalogueId
    title: str = Field(min_length=1, max_length=140)
    outcome: str = Field(min_length=1, max_length=800)
    jobs: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    aliases: tuple[_CatalogueId, ...] = Field(
        max_length=20, json_schema_extra={"uniqueItems": True}
    )
    member_capability_ids: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=80, json_schema_extra={"uniqueItems": True}
    )
    components: tuple[CapabilityComponentV2, ...] = Field(
        min_length=1,
        max_length=120,
        json_schema_extra={
            "uniqueItems": True,
            UNIQUE_COMPONENT_IDENTITY_KEYWORD: True,
        },
    )
    assessment: CapabilityAssessmentV2

    @field_validator("jobs", "aliases", "member_capability_ids")
    @classmethod
    def _ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("duplicate id in capability family")
        return values

    @field_validator("title", "outcome")
    @classmethod
    def _family_text_is_safe(cls, value: str) -> str:
        if _CONTROL_RE.search(value):
            raise ValueError("capability family text must be one bounded line")
        return value

    @field_validator("components")
    @classmethod
    def _components_are_unique(
        cls, values: tuple[CapabilityComponentV2, ...]
    ) -> tuple[CapabilityComponentV2, ...]:
        identities: list[tuple[object, ...]] = []
        for component in values:
            if isinstance(component, CapabilityReferenceV2):
                identity = ("capability", component.capability_id)
            elif isinstance(component, McpToolReferenceV2):
                identity = ("mcp-tool", component.server_id, component.tool_name)
            elif isinstance(component, NangoProviderReferenceV2):
                identity = ("nango-provider", component.provider_id)
            else:
                identity = ("source-component", component.component_id)
            identities.append(identity)
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate component identity in capability family")
        return values


class CatalogueV2(InventoriedModel):
    jobs_taxonomy: tuple[JobTaxonomyEntryV2, ...] = Field(
        min_length=1,
        max_length=80,
        json_schema_extra={
            "uniqueItems": True,
            UNIQUE_BY_KEYWORD: "job_id",
        },
    )
    capabilities: tuple[CatalogueCapabilityEntryV2, ...] = Field(
        min_length=1,
        max_length=300,
        json_schema_extra={
            "uniqueItems": True,
            UNIQUE_BY_KEYWORD: "capability_id",
        },
    )
    capability_aliases: tuple[CapabilityAliasV2, ...] = Field(
        default=(),
        max_length=300,
        json_schema_extra={"uniqueItems": True, UNIQUE_BY_KEYWORD: "alias"},
    )
    capability_families: tuple[CapabilityFamilyV2, ...] = Field(
        default=(),
        max_length=80,
        json_schema_extra={"uniqueItems": True, UNIQUE_BY_KEYWORD: "family_id"},
    )
    portable_brief: PortableBriefContractV2

    @model_validator(mode="after")
    def _cross_references_are_closed(self) -> CatalogueV2:
        job_ids = [job.job_id for job in self.jobs_taxonomy]
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("duplicate jobs taxonomy id")
        capability_ids = [capability.capability_id for capability in self.capabilities]
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("duplicate capability id")
        known_jobs = set(job_ids)
        for capability in self.capabilities:
            unknown = sorted(set(capability.jobs) - known_jobs)
            if unknown:
                raise ValueError(
                    f"capability {capability.capability_id!r} references unknown job(s): "
                    f"{', '.join(unknown)}"
                )

        # Aliases form one closed namespace over canonical capabilities.  A
        # duplicate or target typo is a schema error, never an unresolved
        # display hint.
        aliases = [item.alias for item in self.capability_aliases]
        if len(set(aliases)) != len(aliases):
            raise ValueError("duplicate capability alias")
        canonical_ids = set(capability_ids)
        colliding_aliases = sorted(set(aliases) & canonical_ids)
        if colliding_aliases:
            raise ValueError(
                "capability aliases cannot collide with canonical IDs: "
                + ", ".join(colliding_aliases)
            )
        for item in self.capability_aliases:
            if item.capability_id not in canonical_ids:
                raise ValueError(
                    f"capability alias {item.alias!r} targets unknown capability "
                    f"{item.capability_id!r}"
                )

        # MCP server names are a second lookup key used by typed tool
        # references.  Keep them unique and outside the canonical capability
        # namespace before any family component can resolve one.
        mcp_server_names = [
            entry.server_name
            for entry in self.capabilities
            if isinstance(entry, McpServerCapabilityEntryV2)
        ]
        duplicate_server_names = sorted(
            name
            for name in set(mcp_server_names)
            if mcp_server_names.count(name) > 1
        )
        if duplicate_server_names:
            raise ValueError(
                "duplicate MCP server_name: " + ", ".join(duplicate_server_names)
            )
        colliding_server_names = sorted(set(mcp_server_names) & canonical_ids)
        if colliding_server_names:
            raise ValueError(
                "MCP server_name cannot collide with a capability ID: "
                + ", ".join(colliding_server_names)
            )

        # Family IDs and aliases share a namespace so a producer cannot make
        # two different outcomes resolve from one human-facing name.
        family_ids = [family.family_id for family in self.capability_families]
        if len(set(family_ids)) != len(family_ids):
            raise ValueError("duplicate capability family id")
        family_id_collisions = sorted(set(family_ids) & (canonical_ids | set(aliases)))
        if family_id_collisions:
            collisions = set(family_id_collisions)
            namespaces: list[str] = []
            if collisions & canonical_ids:
                namespaces.append("canonical capability IDs")
            if collisions & set(aliases):
                namespaces.append("capability aliases")
            raise ValueError(
                "capability family IDs cannot collide with "
                + " or ".join(namespaces)
                + ": "
                + ", ".join(family_id_collisions)
            )
        family_aliases = [alias for family in self.capability_families for alias in family.aliases]
        if len(set(family_aliases)) != len(family_aliases):
            raise ValueError("duplicate capability family alias")
        family_alias_collisions = sorted(
            set(family_aliases) & (canonical_ids | set(family_ids) | set(aliases))
        )
        if family_alias_collisions:
            raise ValueError(
                "capability family aliases cannot collide with canonical IDs, "
                "capability aliases, or family IDs: "
                + ", ".join(family_alias_collisions)
            )
        for family in self.capability_families:
            unknown_family_jobs = sorted(set(family.jobs) - known_jobs)
            if unknown_family_jobs:
                raise ValueError(
                    f"capability family {family.family_id!r} references unknown job(s): "
                    + ", ".join(unknown_family_jobs)
                )
            unknown_members = sorted(set(family.member_capability_ids) - canonical_ids)
            if unknown_members:
                raise ValueError(
                    f"capability family {family.family_id!r} references unknown member "
                    "capability ID(s): "
                    + ", ".join(unknown_members)
                )
            self._validate_family_components(family, canonical_ids)
        return self

    def _validate_family_components(
        self, family: CapabilityFamilyV2, canonical_ids: set[str]
    ) -> None:
        """Validate component references against this catalogue's leaf truth."""
        family_members = set(family.member_capability_ids)
        mcp_by_id: dict[str, McpServerCapabilityEntryV2] = {}
        for entry in self.capabilities:
            if isinstance(entry, McpServerCapabilityEntryV2):
                mcp_by_id[entry.capability_id] = entry
                mcp_by_id[entry.server_name] = entry

        for component in family.components:
            if isinstance(component, CapabilityReferenceV2):
                if component.capability_id not in canonical_ids:
                    raise ValueError(
                        f"capability family {family.family_id!r} component references "
                        f"unknown capability {component.capability_id!r}"
                    )
                if component.capability_id not in family_members:
                    raise ValueError(
                        f"capability family {family.family_id!r} component references "
                        f"non-member capability {component.capability_id!r}"
                    )
            elif isinstance(component, McpToolReferenceV2):
                server = mcp_by_id.get(component.server_id)
                if server is None:
                    raise ValueError(
                        f"capability family {family.family_id!r} component references "
                        f"unknown MCP server {component.server_id!r}"
                    )
                if server.capability_id not in family_members:
                    raise ValueError(
                        f"capability family {family.family_id!r} component references "
                        f"tool on non-member MCP server {server.capability_id!r}"
                    )
                if server.tool_inventory != "complete":
                    raise ValueError(
                        f"capability family {family.family_id!r} MCP server "
                        f"{component.server_id!r} has no complete tool inventory"
                    )
                if component.tool_name not in server.tools:
                    raise ValueError(
                        f"capability family {family.family_id!r} references unknown "
                        f"tool {component.tool_name!r} on MCP server {server.server_name!r}"
                    )



class SignedCatalogueEnvelopeV2(InventoriedModel):
    metadata: CatalogueMetadataV2
    catalogue: CatalogueV2
    signature: str = Field(min_length=1)

    # The exact bytes whose signature was verified, kept so the store can
    # persist them verbatim rather than a re-serialised model. Re-dumping
    # the model can add a field the signed original did not carry (a new
    # default), and the offline re-verification would then fail on a
    # catalogue that was perfectly valid. A private attribute is not a
    # model field: it is never serialised, inventoried, or signed.
    _signed_json: str | None = PrivateAttr(default=None)


class VerifiedCatalogueCacheV2(InventoriedModel):
    verified_envelope_json: str = Field(min_length=1)
    highest_catalog_version: int = Field(ge=1)
    verified_at: datetime

    @field_validator("verified_at")
    @classmethod
    def _verified_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware")
        return value


@dataclass(frozen=True)
class VerifiedCatalogueStateV2:
    status: Literal["verified", "stale"]
    catalogue: SignedCatalogueEnvelopeV2 | None
    message: str


def _parse_envelope(raw_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise CatalogueVerificationError(f"malformed catalogue JSON: {exc.msg}") from exc
    envelope = _require_mapping(parsed, "catalogue envelope")
    for key in ("metadata", "catalogue", "signature"):
        if key not in envelope:
            raise CatalogueVerificationError(f"catalogue envelope missing {key!r}")
    extra = set(envelope) - {"metadata", "catalogue", "signature"}
    if extra:
        raise CatalogueVerificationError(f"catalogue envelope has unknown field(s): {extra}")
    return envelope


def _verify_signature(envelope: dict[str, Any], keyring: KeyRing) -> None:
    metadata = _require_mapping(envelope.get("metadata"), "catalogue metadata")
    key_id = metadata.get("key_id")
    if not isinstance(key_id, str):
        raise CatalogueVerificationError("catalogue metadata key_id must be a string")
    signature_text = envelope.get("signature")
    if not isinstance(signature_text, str):
        raise CatalogueVerificationError("catalogue signature must be a string")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except binascii.Error as exc:
        raise CatalogueVerificationError("catalogue signature is not base64") from exc
    try:
        keyring.public_key(key_id).verify(signature, canonical_signed_payload(envelope))
    except InvalidSignature as exc:
        raise CatalogueVerificationError("catalogue signature verification failed") from exc


def verify_catalogue_envelope(
    raw_json: str,
    *,
    keyring: KeyRing,
    now: datetime | None = None,
    highest_verified_catalog_version: int | None = None,
    allow_expired: bool = False,
) -> SignedCatalogueEnvelopeV2:
    """Verify and parse a signed Catalogue v2 envelope.

    The signature is checked before pydantic model construction, so tampered
    signed bytes fail as a signature failure even if their schema still looks
    valid.
    """
    envelope = _parse_envelope(raw_json)
    _verify_signature(envelope, keyring)
    try:
        verified = SignedCatalogueEnvelopeV2.model_validate(envelope)
    except ValidationError as exc:
        raise CatalogueVerificationError("catalogue schema validation failed") from exc
    verified._signed_json = raw_json
    current_time = now or _utcnow()
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise CatalogueVerificationError("verification time must be timezone-aware")
    if verified.metadata.contract_version != _CONTRACT_VERSION:
        raise CatalogueVerificationError("catalogue contract version is not supported")
    if verified.metadata.expires_at < current_time and not allow_expired:
        raise CatalogueVerificationError("catalogue has expired")
    if (
        highest_verified_catalog_version is not None
        and verified.metadata.catalog_version < highest_verified_catalog_version
    ):
        raise CatalogueVerificationError(
            f"catalogue rollback refused: version {verified.metadata.catalog_version} "
            f"is older than highest verified version {highest_verified_catalog_version}"
        )
    return verified


def verify_catalogue_envelope_for_stale_display(
    raw_json: str,
    *,
    keyring: KeyRing,
    highest_verified_catalog_version: int | None = None,
) -> SignedCatalogueEnvelopeV2:
    """Verify a cached envelope for stale/offline display only.

    This deliberately does not enforce ``expires_at`` because its caller is
    already labelling the result stale and non-usable. Signature, schema,
    contract version, and rollback checks still fail closed.
    """
    envelope = _parse_envelope(raw_json)
    _verify_signature(envelope, keyring)
    verified = SignedCatalogueEnvelopeV2.model_validate(envelope)
    verified._signed_json = raw_json
    if verified.metadata.contract_version != _CONTRACT_VERSION:
        raise CatalogueVerificationError("catalogue contract version is not supported")
    if (
        highest_verified_catalog_version is not None
        and verified.metadata.catalog_version < highest_verified_catalog_version
    ):
        raise CatalogueVerificationError(
            f"catalogue rollback refused: version {verified.metadata.catalog_version} "
            f"is older than highest verified version {highest_verified_catalog_version}"
        )
    return verified


def capability_class_of(entry: CatalogueCapabilityEntryV2) -> CapabilityClassV2:
    """The entry's class; a legacy skill-only entry reads as an active skill."""
    return getattr(entry, "capability_class", "active-skill")


def capability_availability_of(entry: CatalogueCapabilityEntryV2) -> CapabilityAvailabilityV2:
    """The entry's availability; a legacy skill-only entry reads as active."""
    return getattr(entry, "availability", "active")


def capability_is_active(entry: CatalogueCapabilityEntryV2) -> bool:
    """Whether consumers may offer this entry as an active recommendation.

    A ``dormant`` or ``parked`` entry validates and may be displayed as a
    fact about Dex, but must never enter the active recommendation set.
    """
    return capability_availability_of(entry) == "active"


def capability_class_fact_lines(entry: CatalogueCapabilityEntryV2) -> list[str]:
    """The class-specific facts an entry carries, as plain unescaped text."""
    if isinstance(entry, McpServerCapabilityEntryV2):
        return [
            f"MCP server {entry.server_name} exposing {entry.tool_count} tool(s), "
            f"for example: {', '.join(entry.example_tools)}.",
        ]
    if isinstance(entry, ScheduledAutomationCapabilityEntryV2):
        return [
            f"Scheduled automation {entry.automation_label}; cadence: {entry.cadence}; "
            f"runs at load: {'yes' if entry.run_at_load else 'no'}.",
        ]
    if isinstance(entry, SystemEngineCapabilityEntryV2):
        return [
            f"System engine of {entry.component_count} component(s), "
            f"for example: {', '.join(entry.example_components)}.",
        ]
    return []


def render_capability_entry_html(entry: CatalogueCapabilityEntryV2) -> str:
    """Render a catalogue entry as inert HTML text for local Lens pages."""
    evidence = "".join(
        "<li>"
        f"<strong>{html.escape(item.level)}</strong>: "
        f"{html.escape(item.summary)} "
        f"<span>{html.escape(item.limitations)}</span>"
        "</li>"
        for item in entry.evidence
    )
    brief = getattr(entry, "portable_brief", None)
    if brief is not None:
        heading = f"<h3>{html.escape(brief.goal)}</h3>"
        notes = "".join(f"<li>{html.escape(note)}</li>" for note in brief.method_outline)
    else:
        # Only a skill has a rebuild brief; the other classes show their own
        # facts instead of a fabricated method.
        heading = f"<h3>{html.escape(entry.title)}</h3>"
        notes = "".join(
            f"<li>{html.escape(line)}</li>" for line in capability_class_fact_lines(entry)
        )
    return (
        "<article>"
        f"<h2>{html.escape(entry.title)}</h2>"
        f"<p>{html.escape(entry.summary)}</p>"
        f"{heading}"
        f"<ul>{evidence}</ul>"
        f"<ol>{notes}</ol>"
        "</article>"
    )


class VerifiedCatalogueStore:
    """Persist and re-verify the last verified public Dex catalogue."""

    def __init__(self, app_storage: Path) -> None:
        self.app_storage = app_storage
        self.cache_path = app_storage / _CACHE_FILE

    def highest_verified_catalog_version(self) -> int | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cache = VerifiedCatalogueCacheV2.model_validate(payload)
        except Exception as exc:
            raise CatalogueVerificationError("stored catalogue cache is unreadable") from exc
        return cache.highest_catalog_version

    def _highest_verified_catalog_version_for_save(self) -> int | None:
        try:
            return self.highest_verified_catalog_version()
        except CatalogueVerificationError:
            return None

    def save_verified(self, verified: SignedCatalogueEnvelopeV2) -> None:
        highest = self._highest_verified_catalog_version_for_save()
        if highest is not None and verified.metadata.catalog_version < highest:
            raise CatalogueVerificationError(
                f"catalogue rollback refused: version {verified.metadata.catalog_version} "
                f"is older than highest verified version {highest}"
            )
        self.app_storage.mkdir(parents=True, exist_ok=True)
        cache = VerifiedCatalogueCacheV2(
            verified_envelope_json=(verified._signed_json or verified.model_dump_json()),
            highest_catalog_version=verified.metadata.catalog_version,
            verified_at=_utcnow(),
        )
        self.cache_path.write_text(
            json.dumps(cache.dump_for_storage(), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def load_last_verified(
        self, *, keyring: KeyRing, now: datetime | None = None
    ) -> SignedCatalogueEnvelopeV2:
        if not self.cache_path.exists():
            raise CatalogueVerificationError("no stored verified catalogue")
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cache = VerifiedCatalogueCacheV2.model_validate(payload)
        except Exception as exc:
            raise CatalogueVerificationError("stored catalogue cache is unreadable") from exc
        return verify_catalogue_envelope(
            cache.verified_envelope_json,
            keyring=keyring,
            now=now,
            highest_verified_catalog_version=cache.highest_catalog_version,
        )

    def load_last_verified_stale(self, *, keyring: KeyRing) -> SignedCatalogueEnvelopeV2:
        """Load a signed cached catalogue for labelled stale/offline display."""
        state = self.load_last_verified_state(keyring=keyring)
        if state.catalogue is None:
            raise CatalogueVerificationError("no stored verified catalogue")
        return state.catalogue

    def load_last_verified_state(
        self, *, keyring: KeyRing, now: datetime | None = None
    ) -> VerifiedCatalogueStateV2:
        if not self.cache_path.exists():
            return VerifiedCatalogueStateV2(
                status="stale",
                catalogue=None,
                message="No Dex catalogue has ever been verified on this machine.",
            )
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cache = VerifiedCatalogueCacheV2.model_validate(payload)
        except Exception as exc:
            raise CatalogueVerificationError("stored catalogue cache is unreadable") from exc
        current_time = now or _utcnow()
        verified = verify_catalogue_envelope(
            cache.verified_envelope_json,
            keyring=keyring,
            now=current_time,
            highest_verified_catalog_version=cache.highest_catalog_version,
            allow_expired=True,
        )
        if verified.metadata.expires_at < current_time:
            return VerifiedCatalogueStateV2(
                status="stale",
                catalogue=verified,
                message=(
                    "Dex catalogue signature is still valid, but the catalogue has expired; "
                    "showing it as stale until Lens can refresh."
                ),
            )
        return VerifiedCatalogueStateV2(
            status="verified",
            catalogue=verified,
            message="Dex catalogue is verified and current.",
        )
