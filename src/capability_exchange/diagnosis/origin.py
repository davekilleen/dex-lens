"""Signed-identity extraction and fingerprint-wide authorship derivation.

This module owns the two deterministic derivations behind the authorship
axis (:class:`~capability_exchange.diagnosis.observations.ObservationOrigin`):
which kind-qualified identities the signature-verified catalogue names, and
how a whole fingerprint classifies against them.  Both are pure functions of
already-verified inputs; nothing here reads storage or trusts a stored flag,
so every consumer re-derives rather than reloading (the
RISK-EXTERNAL-PASS-2026-09-07 A1 lesson).
"""

from __future__ import annotations

from collections.abc import Collection

from capability_exchange.catalogue.v2 import (
    CatalogueV2,
    McpServerCapabilityEntryV2,
    NangoProviderReferenceV2,
    SourceComponentReferenceV2,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    ObservationKind,
    ObservationOrigin,
    derive_observation_origin,
    observation_id_for,
    signed_identity_key,
)
from capability_exchange.diagnosis.significant_families import (
    _aliases_by_target,
    _expected_observation_kind,
)

__all__ = [
    "derive_observation_origins",
    "signed_identity_keys_for",
    "unique_to_you_observation_ids",
]

#: The observation kinds under which a signed source component may be
#: observed locally — the union the family matcher's reviewed profiles admit.
_SOURCE_COMPONENT_KINDS = (
    ObservationKind.AUTOMATION,
    ObservationKind.HEALTH_CHECK,
    ObservationKind.INTEGRATION_REGISTRY,
    ObservationKind.RECOVERY_PROOF,
)

#: Dex's own release record.  The discovery adapter mints exactly this
#: identity, by a closed rule, from a Dex lineage file (`.dex-version` or its
#: CHANGELOG); it is Dex's record of itself, never the person's authored work.
_DEX_RELEASE_KEY = signed_identity_key(ObservationKind.RELEASE, "dex-core")


def signed_identity_keys_for(catalogue: CatalogueV2) -> frozenset[str]:
    """Every kind-qualified identity the signed catalogue names.

    The namespace mirrors the reviewed exact matcher in
    ``significant_families``: capability ids under their expected observation
    kind, signed aliases, MCP server names, signed MCP tool names as
    ``server.tool`` tokens across every signed server identity, and — where a
    signed family contract exists — its provider and source-component ids.
    Nothing enters from unsigned data, labels, or similarity.
    """

    if not isinstance(catalogue, CatalogueV2):
        raise TypeError("catalogue must be a validated CatalogueV2")
    aliases_by_target = _aliases_by_target(catalogue)
    keys: set[str] = {_DEX_RELEASE_KEY}
    for entry in catalogue.capabilities:
        expected_kind = _expected_observation_kind(entry)
        if expected_kind is None:
            # System engines have no local detector kind: a local item named
            # after one is not that engine, so its name mints no stock claim.
            continue
        identities = {entry.capability_id}
        identities.update(aliases_by_target.get(entry.capability_id, frozenset()))
        if isinstance(entry, McpServerCapabilityEntryV2):
            identities.add(entry.server_name)
            tool_names = {*entry.tools, *entry.example_tools}
            keys.update(
                signed_identity_key(
                    ObservationKind.MCP_TOOL, f"{server_identity}.{tool_name}"
                )
                for server_identity in identities
                for tool_name in tool_names
            )
        keys.update(
            signed_identity_key(expected_kind, identity) for identity in identities
        )
    for family in catalogue.capability_families:
        for component in family.components:
            if isinstance(component, NangoProviderReferenceV2):
                keys.add(
                    signed_identity_key(
                        ObservationKind.INTEGRATION_PROVIDER, component.provider_id
                    )
                )
            elif isinstance(component, SourceComponentReferenceV2):
                keys.update(
                    signed_identity_key(kind, component.component_id)
                    for kind in _SOURCE_COMPONENT_KINDS
                )
    return frozenset(keys)


def derive_observation_origins(
    fingerprint: EvidenceFingerprint,
    *,
    signed_identity_keys: Collection[str],
) -> dict[str, ObservationOrigin]:
    """Classify every captured observation, keyed by its observation id."""

    keys = frozenset(signed_identity_keys)
    return {
        observation_id_for(observation): derive_observation_origin(
            observation, signed_identity_keys=keys
        )
        for observation in fingerprint.observations
    }


def unique_to_you_observation_ids(
    fingerprint: EvidenceFingerprint,
    *,
    signed_identity_keys: Collection[str],
) -> tuple[str, ...]:
    """The engine-owned unique-to-you candidates: authored observations only.

    By construction an authored observation matches no signed identity and did
    not arrive with the assistant, so this is exactly the deterministic
    candidate list both reciprocal share-back moments draw from.  The host can
    read it aloud but cannot author a row of it.
    """

    origins = derive_observation_origins(
        fingerprint, signed_identity_keys=signed_identity_keys
    )
    return tuple(
        sorted(
            observation_id
            for observation_id, origin in origins.items()
            if origin is ObservationOrigin.AUTHORED
        )
    )
