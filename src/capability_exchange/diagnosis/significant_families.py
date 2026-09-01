"""Pure, deterministic evidence matching for signed capability families.

This module deliberately reports *overlap*, not equivalence.  A local item
with an exact signed identity can prove that a similarly named component is
present or configured.  It cannot prove that the local method, behaviour, or
outcome is the same as Dex's.  Every match therefore remains evidence-bound
and every unsupported component remains explicit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from capability_exchange.catalogue.v2 import (
    ActiveSkillCapabilityEntryV2,
    AutomaticAssessmentV2,
    CapabilityComponentV2,
    CapabilityReferenceV2,
    CatalogueCapabilityEntryV2,
    CatalogueV2,
    LegacySkillCapabilityEntryV2,
    ManualOnlyAssessmentV2,
    McpServerCapabilityEntryV2,
    McpToolReferenceV2,
    NangoProviderReferenceV2,
    ScheduledAutomationCapabilityEntryV2,
    SourceComponentReferenceV2,
    SystemEngineCapabilityEntryV2,
)
from capability_exchange.diagnosis.families import (
    FamilyAvailability,
    summarise_family,
)
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    EvidenceFingerprint,
    HealthState,
    Observation,
    ObservationKind,
    RuntimeState,
)
from capability_exchange.evidence import supports_claims

__all__ = [
    "ComponentMatchBasis",
    "FamilyAssessmentDisposition",
    "MatchedFamilyComponent",
    "SignificantFamilyAssessment",
    "UnsupportedAssessmentProfileError",
    "assess_significant_families",
]


class UnsupportedAssessmentProfileError(ValueError):
    """A signed automatic profile has no reviewed local detector."""


class ComponentMatchBasis(StrEnum):
    """The closed reason an exact local observation supports one component."""

    EXACT_CAPABILITY_IDENTITY = "exact-capability-identity"
    SIGNED_CAPABILITY_ALIAS = "signed-capability-alias"
    MCP_SERVER_CONFIGURATION = "mcp-server-configuration"
    EXACT_MCP_TOOL_IDENTITY = "exact-mcp-tool-identity"
    EXACT_PROVIDER_IDENTITY = "exact-provider-identity"
    EXACT_SOURCE_EVIDENCE = "exact-source-evidence"


class FamilyAssessmentDisposition(StrEnum):
    """One conservative local-evidence disposition for a signed family."""

    NOT_ASSESSED = "not-assessed"
    UNRESOLVED = "unresolved"
    PARTIAL_OVERLAP = "partial-overlap"
    OVERLAP_OBSERVED = "overlap-observed"
    NOT_RECOMMENDABLE = "not-recommendable"


@dataclass(frozen=True)
class MatchedFamilyComponent:
    """One signed component with exact, claim-supporting local observations."""

    component_reference: str
    observation_ids: tuple[str, ...]
    evidence_references: tuple[str, ...]
    match_bases: tuple[ComponentMatchBasis, ...]

    @property
    def method_equivalent(self) -> Literal[False]:
        """Identity overlap is never a claim of equivalent implementation."""

        return False


@dataclass(frozen=True)
class SignificantFamilyAssessment:
    """Signed family availability alongside conservative local evidence."""

    family_id: str
    signed_availability: FamilyAvailability
    available_member_ids: tuple[str, ...]
    unavailable_member_ids: tuple[str, ...]
    recommendable_member_ids: tuple[str, ...]
    matched_components: tuple[MatchedFamilyComponent, ...]
    matched_observation_ids: tuple[str, ...]
    unresolved_components: tuple[str, ...]
    evidence_references: tuple[str, ...]
    disposition: FamilyAssessmentDisposition
    reason: str


@dataclass(frozen=True)
class _ProfileRules:
    component_types: frozenset[str]
    source_observation_kinds: frozenset[ObservationKind] = frozenset()


# This table is the executable allowlist.  Catalogue data can select one of
# these reviewed profiles but cannot name code, add a kind, or broaden a read.
_PROFILE_RULES: dict[str, _ProfileRules] = {
    "catalogue": _ProfileRules(frozenset({"capability", "mcp-tool"})),
    "mcp": _ProfileRules(
        frozenset({"capability", "mcp-tool", "source-component"}),
        frozenset({ObservationKind.INTEGRATION_REGISTRY}),
    ),
    "mcp-tool": _ProfileRules(frozenset({"mcp-tool"})),
    "provider": _ProfileRules(
        frozenset({"capability", "nango-provider", "source-component"}),
        frozenset({ObservationKind.INTEGRATION_REGISTRY}),
    ),
    "scheduled-automation": _ProfileRules(
        frozenset({"capability", "mcp-tool", "source-component"}),
        frozenset({ObservationKind.AUTOMATION}),
    ),
    "filesystem": _ProfileRules(
        frozenset({"capability", "source-component"}),
        frozenset({ObservationKind.RECOVERY_PROOF}),
    ),
    "source-component": _ProfileRules(
        frozenset({"source-component"}),
        frozenset(
            {
                ObservationKind.AUTOMATION,
                ObservationKind.HEALTH_CHECK,
                ObservationKind.INTEGRATION_REGISTRY,
                ObservationKind.RECOVERY_PROOF,
            }
        ),
    ),
    "health": _ProfileRules(
        frozenset({"capability", "mcp-tool", "source-component"}),
        frozenset({ObservationKind.HEALTH_CHECK, ObservationKind.RECOVERY_PROOF}),
    ),
    "doctor": _ProfileRules(
        frozenset({"capability", "source-component"}),
        frozenset({ObservationKind.HEALTH_CHECK, ObservationKind.RECOVERY_PROOF}),
    ),
}

_PRESENT_CONFIGURATION_STATES = frozenset(
    {
        ConfigurationState.DECLARED,
        ConfigurationState.IMPLEMENTED,
        ConfigurationState.INSTALLED,
        ConfigurationState.ENABLED,
        ConfigurationState.DISABLED,
    }
)
_PRESENT_RUNTIME_STATES = frozenset(
    {
        RuntimeState.LOADED,
        RuntimeState.RUNNING,
        RuntimeState.RECENTLY_RUN,
        RuntimeState.OUTCOME_VERIFIED,
        RuntimeState.STALE,
        RuntimeState.DISABLED,
    }
)
_PRESENT_HEALTH_STATES = frozenset(
    {
        HealthState.HEALTHY,
        HealthState.BROKEN,
        HealthState.STALE,
        HealthState.DISABLED,
    }
)


def _component_reference(component: CapabilityComponentV2) -> str:
    if isinstance(component, CapabilityReferenceV2):
        return f"capability:{component.capability_id}"
    if isinstance(component, McpToolReferenceV2):
        return f"mcp-tool:{component.server_id}:{component.tool_name}"
    if isinstance(component, NangoProviderReferenceV2):
        return f"nango-provider:{component.provider_id}"
    if isinstance(component, SourceComponentReferenceV2):
        return f"source-component:{component.component_id}"
    raise TypeError("family component must be a validated CapabilityComponentV2")


def _observation_can_support_presence(
    observation: Observation,
    *,
    fingerprint: EvidenceFingerprint,
) -> bool:
    if not supports_claims(observation.evidence.effective_state(now=fingerprint.collected_at)):
        return False
    return (
        observation.configuration_state in _PRESENT_CONFIGURATION_STATES
        or observation.runtime_state in _PRESENT_RUNTIME_STATES
        or observation.health_state in _PRESENT_HEALTH_STATES
    )


def _observation_index(
    fingerprint: EvidenceFingerprint,
) -> dict[ObservationKind, tuple[Observation, ...]]:
    grouped: dict[ObservationKind, list[Observation]] = defaultdict(list)
    for observation in fingerprint.observations:
        if _observation_can_support_presence(observation, fingerprint=fingerprint):
            grouped[observation.kind].append(observation)
    return {
        kind: tuple(sorted(items, key=lambda item: item.observation_id))
        for kind, items in grouped.items()
    }


def _aliases_by_target(catalogue: CatalogueV2) -> dict[str, frozenset[str]]:
    collected: dict[str, set[str]] = defaultdict(set)
    for alias in catalogue.capability_aliases:
        # CatalogueV2 validation guarantees the target is a signed canonical
        # capability.  No family alias, display label, or local guess enters
        # this namespace.
        collected[alias.capability_id].add(alias.alias)
    return {target: frozenset(aliases) for target, aliases in collected.items()}


def _expected_observation_kind(
    entry: CatalogueCapabilityEntryV2,
) -> ObservationKind | None:
    if isinstance(entry, (LegacySkillCapabilityEntryV2, ActiveSkillCapabilityEntryV2)):
        return ObservationKind.SKILL
    if isinstance(entry, McpServerCapabilityEntryV2):
        return ObservationKind.MCP_SERVER
    if isinstance(entry, ScheduledAutomationCapabilityEntryV2):
        return ObservationKind.AUTOMATION
    if isinstance(entry, SystemEngineCapabilityEntryV2):
        # The fingerprint has no generic engine observation.  Matching a
        # similarly named skill or file would manufacture an unsupported
        # equivalence, so engines remain unresolved without a typed detector.
        return None
    raise TypeError("catalogue capability must be a validated capability entry")


def _capability_matches(
    component: CapabilityReferenceV2,
    *,
    capabilities: dict[str, CatalogueCapabilityEntryV2],
    aliases_by_target: dict[str, frozenset[str]],
    observations: dict[ObservationKind, tuple[Observation, ...]],
) -> tuple[tuple[Observation, ComponentMatchBasis], ...]:
    entry = capabilities[component.capability_id]
    expected_kind = _expected_observation_kind(entry)
    if expected_kind is None:
        return ()
    aliases = aliases_by_target.get(component.capability_id, frozenset())
    identities = {component.capability_id, *aliases}
    if isinstance(entry, McpServerCapabilityEntryV2):
        identities.add(entry.server_name)
    matches: list[tuple[Observation, ComponentMatchBasis]] = []
    for observation in observations.get(expected_kind, ()):
        if observation.identity not in identities:
            continue
        if isinstance(entry, McpServerCapabilityEntryV2):
            basis = ComponentMatchBasis.MCP_SERVER_CONFIGURATION
        elif observation.identity == component.capability_id:
            basis = ComponentMatchBasis.EXACT_CAPABILITY_IDENTITY
        else:
            basis = ComponentMatchBasis.SIGNED_CAPABILITY_ALIAS
        matches.append((observation, basis))
    return tuple(matches)


def _mcp_tool_matches(
    component: McpToolReferenceV2,
    *,
    capabilities: dict[str, CatalogueCapabilityEntryV2],
    aliases_by_target: dict[str, frozenset[str]],
    observations: dict[ObservationKind, tuple[Observation, ...]],
) -> tuple[tuple[Observation, ComponentMatchBasis], ...]:
    entry = capabilities.get(component.server_id)
    if entry is None:
        entry = next(
            (
                candidate
                for candidate in capabilities.values()
                if isinstance(candidate, McpServerCapabilityEntryV2)
                and candidate.server_name == component.server_id
            ),
            None,
        )
    if not isinstance(entry, McpServerCapabilityEntryV2):
        # CatalogueV2 validation normally makes this impossible.  The guard
        # keeps model_construct or a future caller from turning a malformed
        # server reference into a local match.
        return ()
    server_identities = {
        component.server_id,
        entry.server_name,
        *aliases_by_target.get(entry.capability_id, frozenset()),
    }
    # Observation identities use a dot because the closed Observation id
    # grammar deliberately excludes colons.  The server identity remains in
    # the token so the same tool name on two servers cannot collide.
    exact_identities = {
        f"{server_identity}.{component.tool_name}" for server_identity in server_identities
    }
    return tuple(
        (observation, ComponentMatchBasis.EXACT_MCP_TOOL_IDENTITY)
        for observation in observations.get(ObservationKind.MCP_TOOL, ())
        if observation.identity in exact_identities
    )


def _provider_matches(
    component: NangoProviderReferenceV2,
    *,
    observations: dict[ObservationKind, tuple[Observation, ...]],
) -> tuple[tuple[Observation, ComponentMatchBasis], ...]:
    return tuple(
        (observation, ComponentMatchBasis.EXACT_PROVIDER_IDENTITY)
        for observation in observations.get(ObservationKind.INTEGRATION_PROVIDER, ())
        if observation.identity == component.provider_id
    )


def _source_matches(
    component: SourceComponentReferenceV2,
    *,
    rules: _ProfileRules,
    observations: dict[ObservationKind, tuple[Observation, ...]],
) -> tuple[tuple[Observation, ComponentMatchBasis], ...]:
    matches: list[tuple[Observation, ComponentMatchBasis]] = []
    for kind in sorted(rules.source_observation_kinds, key=lambda item: item.value):
        matches.extend(
            (observation, ComponentMatchBasis.EXACT_SOURCE_EVIDENCE)
            for observation in observations.get(kind, ())
            if observation.identity == component.component_id
        )
    return tuple(matches)


def _matches_for_component(
    component: CapabilityComponentV2,
    *,
    rules: _ProfileRules,
    capabilities: dict[str, CatalogueCapabilityEntryV2],
    aliases_by_target: dict[str, frozenset[str]],
    observations: dict[ObservationKind, tuple[Observation, ...]],
) -> tuple[tuple[Observation, ComponentMatchBasis], ...]:
    if component.component_type not in rules.component_types:
        return ()
    if isinstance(component, CapabilityReferenceV2):
        return _capability_matches(
            component,
            capabilities=capabilities,
            aliases_by_target=aliases_by_target,
            observations=observations,
        )
    if isinstance(component, McpToolReferenceV2):
        return _mcp_tool_matches(
            component,
            capabilities=capabilities,
            aliases_by_target=aliases_by_target,
            observations=observations,
        )
    if isinstance(component, NangoProviderReferenceV2):
        return _provider_matches(component, observations=observations)
    if isinstance(component, SourceComponentReferenceV2):
        return _source_matches(component, rules=rules, observations=observations)
    raise TypeError("family component must be a validated CapabilityComponentV2")


def _matched_component(
    component: CapabilityComponentV2,
    matches: tuple[tuple[Observation, ComponentMatchBasis], ...],
) -> MatchedFamilyComponent:
    return MatchedFamilyComponent(
        component_reference=_component_reference(component),
        observation_ids=tuple(sorted({item.observation_id for item, _basis in matches})),
        evidence_references=tuple(sorted({item.evidence.reference for item, _basis in matches})),
        match_bases=tuple(sorted({basis for _item, basis in matches}, key=lambda item: item.value)),
    )


def _reason_for(
    disposition: FamilyAssessmentDisposition,
    *,
    manual_reason: str | None = None,
) -> str:
    if disposition is FamilyAssessmentDisposition.NOT_ASSESSED:
        return manual_reason or "This family requires a person's review."
    if disposition is FamilyAssessmentDisposition.NOT_RECOMMENDABLE:
        return (
            "No signed family member is currently active, so dormant or parked "
            "members cannot be recommended."
        )
    if disposition is FamilyAssessmentDisposition.UNRESOLVED:
        return (
            "No exact supported local evidence matched this signed family. "
            "This is unresolved, not proof that the capability is absent."
        )
    if disposition is FamilyAssessmentDisposition.PARTIAL_OVERLAP:
        return (
            "Exact signed identity evidence overlaps some components; other components "
            "remain unresolved. Identity overlap does not prove method equivalence or "
            "the same outcome."
        )
    return (
        "Every signed component has exact supported identity evidence. This records "
        "overlap only and does not prove method equivalence or the same outcome."
    )


def _validate_profiles(catalogue: CatalogueV2) -> None:
    unknown = sorted(
        {
            str(family.assessment.profile)
            for family in catalogue.capability_families
            if isinstance(family.assessment, AutomaticAssessmentV2)
            and str(family.assessment.profile) not in _PROFILE_RULES
        }
    )
    if unknown:
        raise UnsupportedAssessmentProfileError(
            "unsupported automatic significant-family assessment profile(s): " + ", ".join(unknown)
        )


def assess_significant_families(
    catalogue: CatalogueV2,
    fingerprint: EvidenceFingerprint,
) -> tuple[SignificantFamilyAssessment, ...]:
    """Assess every signed family against exact, supported local observations.

    The function is pure: it reads two already-validated models and returns
    immutable values.  Profiles are validated as a complete set before any
    result is built, so an unknown automatic profile aborts the assessment
    rather than returning a misleading partial answer.
    """

    if not isinstance(catalogue, CatalogueV2):
        raise TypeError("catalogue must be a validated CatalogueV2")
    if not isinstance(fingerprint, EvidenceFingerprint):
        raise TypeError("fingerprint must be a validated EvidenceFingerprint")
    _validate_profiles(catalogue)

    capabilities = {entry.capability_id: entry for entry in catalogue.capabilities}
    aliases_by_target = _aliases_by_target(catalogue)
    observations = _observation_index(fingerprint)
    results: list[SignificantFamilyAssessment] = []

    for family in sorted(catalogue.capability_families, key=lambda item: item.family_id):
        member_entries = tuple(
            capabilities[member_id] for member_id in family.member_capability_ids
        )
        summary = summarise_family(family, member_entries)
        component_references = tuple(
            sorted(_component_reference(component) for component in family.components)
        )

        if isinstance(family.assessment, ManualOnlyAssessmentV2):
            results.append(
                SignificantFamilyAssessment(
                    family_id=family.family_id,
                    signed_availability=summary.availability,
                    available_member_ids=summary.available_member_ids,
                    unavailable_member_ids=summary.unavailable_member_ids,
                    recommendable_member_ids=summary.recommendable_member_ids,
                    matched_components=(),
                    matched_observation_ids=(),
                    unresolved_components=component_references,
                    evidence_references=(),
                    disposition=FamilyAssessmentDisposition.NOT_ASSESSED,
                    reason=_reason_for(
                        FamilyAssessmentDisposition.NOT_ASSESSED,
                        manual_reason=family.assessment.reason,
                    ),
                )
            )
            continue

        rules = _PROFILE_RULES[str(family.assessment.profile)]
        matched: list[MatchedFamilyComponent] = []
        unresolved: list[str] = []
        for component in sorted(family.components, key=_component_reference):
            matches = _matches_for_component(
                component,
                rules=rules,
                capabilities=capabilities,
                aliases_by_target=aliases_by_target,
                observations=observations,
            )
            if matches:
                matched.append(_matched_component(component, matches))
            else:
                unresolved.append(_component_reference(component))

        if summary.availability is FamilyAvailability.UNAVAILABLE:
            disposition = FamilyAssessmentDisposition.NOT_RECOMMENDABLE
        elif not matched:
            disposition = FamilyAssessmentDisposition.UNRESOLVED
        elif unresolved:
            disposition = FamilyAssessmentDisposition.PARTIAL_OVERLAP
        else:
            disposition = FamilyAssessmentDisposition.OVERLAP_OBSERVED

        matched_observation_ids = tuple(
            sorted({item for component in matched for item in component.observation_ids})
        )
        evidence_references = tuple(
            sorted({item for component in matched for item in component.evidence_references})
        )
        results.append(
            SignificantFamilyAssessment(
                family_id=family.family_id,
                signed_availability=summary.availability,
                available_member_ids=summary.available_member_ids,
                unavailable_member_ids=summary.unavailable_member_ids,
                recommendable_member_ids=summary.recommendable_member_ids,
                matched_components=tuple(matched),
                matched_observation_ids=matched_observation_ids,
                unresolved_components=tuple(unresolved),
                evidence_references=evidence_references,
                disposition=disposition,
                reason=_reason_for(disposition),
            )
        )
    return tuple(results)
