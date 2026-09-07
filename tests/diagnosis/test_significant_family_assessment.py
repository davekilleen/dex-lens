"""Deterministic, fail-closed assessment of signed significant families.

The fixtures here are synthetic.  A matching name is useful evidence of local
presence only when the signed contract says how to interpret that identity; it
is never proof that two systems use the same method or produce the same result.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capability_exchange.catalogue.v2 import (
    AutomaticAssessmentV2,
    CapabilityFamilyV2,
    CatalogueV2,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
)
from capability_exchange.diagnosis.significant_families import (
    ComponentMatchBasis,
    FamilyAssessmentDisposition,
    UnsupportedAssessmentProfileError,
    assess_significant_families,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
PROVENANCE = {
    "source_id": "scope:synthetic",
    "source_class": "vault-authored",
    "scope_reference": "scope:sha256:" + "a" * 64,
    "relative_reference": "synthetic/manifest.json",
}


def _job() -> dict[str, object]:
    return {
        "job_id": "keep-work-moving",
        "label": "Keep work moving",
        "description": "Carry useful work through to a checked outcome.",
        "confirmed_gap_signals": ["work repeatedly loses its next step"],
    }


def _shared_fields(capability_id: str, capability_class: str) -> dict[str, object]:
    return {
        "capability_id": capability_id,
        "capability_class": capability_class,
        "impact_tier": "core",
        "availability": "active",
        "title": capability_id.replace("-", " ").title(),
        "summary": "Synthetic capability used to test the deterministic assessor.",
        "value": "Makes one bounded outcome easier to complete.",
        "jobs": ["keep-work-moving"],
        "prerequisites": ["an approved read scope"],
        "trade_offs": ["presence does not prove a working outcome"],
        "evidence": [
            {
                "level": "supported",
                "source": "synthetic test",
                "summary": "Fixture evidence only.",
                "limitations": "No real system was inspected.",
            }
        ],
        "release_provenance": "core-release",
    }


def _skill(capability_id: str, *, availability: str = "active") -> dict[str, object]:
    entry = _shared_fields(capability_id, "active-skill")
    entry.update(
        {
            "availability": availability,
            "compatibility": {
                "host_adapters": ["claude-code"],
                "foundation_capabilities": ["durable-memory-provenance"],
                "minimum_lens_contract": "0.1.0",
                "platforms": ["macos"],
                "needs_hooks": False,
                "needs_mcp": False,
                "host_requirements": ["skills-directory"],
                "limitations": ["Synthetic fixture only."],
            },
            "docs_url": "https://example.invalid/synthetic-capability",
            "since_release": "1.0.0",
            "changed_in": [],
            "portable_brief": {
                "goal": "Recreate one synthetic pattern.",
                "method_outline": ["Inspect only approved evidence."],
                "verification_checklist": ["Confirm the synthetic outcome."],
                "rollback_advice": "Remove the synthetic local note.",
                "safety_notes": ["No changes are made by Lens."],
            },
        }
    )
    return entry


def _mcp(*, server_name: str = "dex-work-mcp") -> dict[str, object]:
    entry = _shared_fields("dex-work-mcp", "mcp-server")
    entry.update(
        {
            "server_name": server_name,
            "tool_count": 1,
            "example_tools": ["create_task"],
            "source_paths": ["core/mcp/work_server.py"],
            "tools": ["create_task"],
            "tool_inventory": "complete",
        }
    )
    return entry


def _automation() -> dict[str, object]:
    entry = _shared_fields("dex-nightly-check", "scheduled-automation")
    entry.update(
        {
            "automation_label": "com.dex.nightly-check",
            "cadence": "nightly",
            "source_paths": ["automations/nightly-check.plist"],
            "installer_path": "scripts/install-nightly-check.sh",
            "program_target": "scripts/nightly-check.py",
            "run_at_load": False,
        }
    )
    return entry


def _parked_engine() -> dict[str, object]:
    entry = _shared_fields("parked-engine", "system-engine")
    entry.update(
        {
            "availability": "parked",
            "source_paths": ["core/parked/engine.py"],
            "component_count": 1,
            "example_components": ["core/parked/engine.py"],
        }
    )
    return entry


def _family(
    family_id: str,
    *,
    profile: str | None,
    members: list[str],
    components: list[dict[str, object]],
) -> dict[str, object]:
    assessment: dict[str, object]
    if profile is None:
        assessment = {
            "mode": "manual-only",
            "reason": "A person must decide whether this private feedback may be shared.",
        }
    else:
        assessment = {"mode": "automatic", "profile": profile}
    return {
        "family_id": family_id,
        "title": family_id.replace("-", " ").title(),
        "outcome": "A synthetic outcome used only to test deterministic matching.",
        "jobs": ["keep-work-moving"],
        "aliases": [f"{family_id}-family"],
        "member_capability_ids": members,
        "components": components,
        "assessment": assessment,
    }


def _catalogue(
    *families: dict[str, object],
    mcp_server_name: str = "dex-work-mcp",
) -> CatalogueV2:
    return CatalogueV2.model_validate(
        {
            "jobs_taxonomy": [_job()],
            "capabilities": [
                _skill("workflow-skill"),
                _skill("dormant-helper", availability="dormant"),
                _mcp(server_name=mcp_server_name),
                _automation(),
                _parked_engine(),
            ],
            "capability_aliases": [
                {"alias": "work-mcp", "capability_id": "dex-work-mcp"},
                {"alias": "workflow-alias", "capability_id": "workflow-skill"},
            ],
            "capability_families": list(families),
            "portable_brief": {
                "format": "markdown",
                "audience": "the person's own AI system",
                "safety_boundary": "guidance only; it changes nothing",
            },
        }
    )


def _observation(
    kind: ObservationKind,
    identity: str,
    *,
    label: str | None = None,
    state: OperationalState = OperationalState.IMPLEMENTED,
    reference: str | None = None,
) -> Observation:
    return Observation(
        kind=kind,
        identity=identity,
        label=label or identity,
        operational_state=state,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference=reference or f"fixture:{kind.value}:{identity}",
        ),
        provenance=PROVENANCE,
    )


def _fingerprint(*observations: Observation) -> EvidenceFingerprint:
    return EvidenceFingerprint(
        adapter_id="synthetic-read-only",
        collected_at=NOW,
        observations=observations,
    )


def test_signed_alias_matches_configuration_but_never_claims_method_equivalence() -> None:
    family = _family(
        "task-continuity",
        profile="mcp",
        members=["dex-work-mcp"],
        components=[
            {"component_type": "capability", "capability_id": "dex-work-mcp"},
            {
                "component_type": "mcp-tool",
                "server_id": "dex-work-mcp",
                "tool_name": "create_task",
            },
        ],
    )
    result = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.MCP_SERVER, "work-mcp")),
    )[0]

    assert result.family_id == "task-continuity"
    assert result.signed_availability.value == "available"
    assert result.disposition is FamilyAssessmentDisposition.PARTIAL_OVERLAP
    assert result.matched_components[0].component_reference == "capability:dex-work-mcp"
    assert result.matched_components[0].match_bases == (
        ComponentMatchBasis.MCP_SERVER_CONFIGURATION,
    )
    assert result.matched_components[0].method_equivalent is False
    assert result.unresolved_components == ("mcp-tool:dex-work-mcp:create_task",)
    assert "does not prove method equivalence" in result.reason


def test_configured_mcp_server_never_proves_tool_execution() -> None:
    family = _family(
        "tool-use",
        profile="mcp",
        members=["dex-work-mcp"],
        components=[
            {
                "component_type": "mcp-tool",
                "server_id": "dex-work-mcp",
                "tool_name": "create_task",
            }
        ],
    )

    configured_only = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.MCP_SERVER, "dex-work-mcp")),
    )[0]
    exact_tool = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.MCP_TOOL, "work-mcp.create_task")),
    )[0]

    assert configured_only.matched_components == ()
    assert configured_only.unresolved_components == ("mcp-tool:dex-work-mcp:create_task",)
    assert exact_tool.matched_components[0].match_bases == (
        ComponentMatchBasis.EXACT_MCP_TOOL_IDENTITY,
    )
    assert exact_tool.matched_components[0].method_equivalent is False


def test_exact_tool_can_use_the_signed_server_name_instead_of_capability_id() -> None:
    family = _family(
        "tool-use",
        profile="mcp",
        members=["dex-work-mcp"],
        components=[
            {
                "component_type": "mcp-tool",
                "server_id": "dex-work",
                "tool_name": "create_task",
            }
        ],
    )
    result = assess_significant_families(
        _catalogue(family, mcp_server_name="dex-work"),
        _fingerprint(_observation(ObservationKind.MCP_TOOL, "dex-work.create_task")),
    )[0]

    assert result.matched_components[0].component_reference == ("mcp-tool:dex-work:create_task")


def test_display_label_and_unsigned_alias_never_match_a_component() -> None:
    family = _family(
        "workflow",
        profile="catalogue",
        members=["workflow-skill"],
        components=[{"component_type": "capability", "capability_id": "workflow-skill"}],
    )
    result = assess_significant_families(
        _catalogue(family),
        _fingerprint(
            _observation(
                ObservationKind.SKILL,
                "unsigned-local-name",
                label="workflow-skill",
            )
        ),
    )[0]

    assert result.matched_components == ()
    assert result.matched_observation_ids == ()
    assert result.disposition is FamilyAssessmentDisposition.UNRESOLVED


def test_source_component_requires_exact_profile_supported_evidence() -> None:
    family = _family(
        "restore-confidence",
        profile="filesystem",
        members=["workflow-skill"],
        components=[{"component_type": "source-component", "component_id": "restore-proof"}],
    )
    wrong_kind = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.SKILL, "restore-proof")),
    )[0]
    exact_supported = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.RECOVERY_PROOF, "restore-proof")),
    )[0]

    assert wrong_kind.unresolved_components == ("source-component:restore-proof",)
    assert exact_supported.matched_components[0].match_bases == (
        ComponentMatchBasis.EXACT_SOURCE_EVIDENCE,
    )


def test_restore_proof_matches_the_signed_vault_backup_source_component() -> None:
    family = _family(
        "backup-and-restore-confidence",
        profile="filesystem",
        members=["workflow-skill"],
        components=[{"component_type": "source-component", "component_id": "vault-backup"}],
    )

    result = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.RECOVERY_PROOF, "vault-backup")),
    )[0]

    assert result.unresolved_components == ()
    assert result.matched_components[0].component_reference == "source-component:vault-backup"
    assert result.matched_components[0].match_bases == (
        ComponentMatchBasis.EXACT_SOURCE_EVIDENCE,
    )


def test_mcp_profile_accepts_only_exact_integration_registry_source_evidence() -> None:
    family = _family(
        "external-task-interoperability",
        profile="mcp",
        members=["dex-work-mcp"],
        components=[
            {
                "component_type": "mcp-tool",
                "server_id": "dex-work-mcp",
                "tool_name": "create_task",
            },
            {
                "component_type": "source-component",
                "component_id": "external-task-sync",
            },
        ],
    )

    configured_server = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.MCP_SERVER, "external-task-sync")),
    )[0]
    generic_registry = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.INTEGRATION_REGISTRY, "local-integrations")),
    )[0]
    exact_registry = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.INTEGRATION_REGISTRY, "external-task-sync")),
    )[0]

    assert configured_server.matched_components == ()
    assert generic_registry.matched_components == ()
    assert exact_registry.matched_components[0].component_reference == (
        "source-component:external-task-sync"
    )
    assert exact_registry.unresolved_components == (
        "mcp-tool:dex-work-mcp:create_task",
    )


def test_all_profiles_in_current_core_preview_have_closed_handlers() -> None:
    families = (
        _family(
            "catalogue-family",
            profile="catalogue",
            members=["workflow-skill"],
            components=[{"component_type": "capability", "capability_id": "workflow-skill"}],
        ),
        _family(
            "mcp-family",
            profile="mcp",
            members=["dex-work-mcp"],
            components=[{"component_type": "capability", "capability_id": "dex-work-mcp"}],
        ),
        _family(
            "provider-family",
            profile="provider",
            members=["workflow-skill"],
            components=[
                {
                    "component_type": "nango-provider",
                    "provider_id": "google-calendar",
                    "source_package": "@nangohq/providers",
                    "source_version": "0.70.5",
                    "dex_support": "supported",
                    "security_vetted": True,
                }
            ],
        ),
        _family(
            "scheduled-family",
            profile="scheduled-automation",
            members=["dex-nightly-check"],
            components=[{"component_type": "capability", "capability_id": "dex-nightly-check"}],
        ),
        _family(
            "filesystem-family",
            profile="filesystem",
            members=["workflow-skill"],
            components=[{"component_type": "source-component", "component_id": "restore-proof"}],
        ),
        _family(
            "health-family",
            profile="health",
            members=["workflow-skill"],
            components=[{"component_type": "source-component", "component_id": "doctor-check"}],
        ),
    )
    fingerprint = _fingerprint(
        _observation(ObservationKind.SKILL, "workflow-skill"),
        _observation(ObservationKind.MCP_SERVER, "dex-work-mcp"),
        _observation(ObservationKind.INTEGRATION_PROVIDER, "google-calendar"),
        _observation(ObservationKind.AUTOMATION, "dex-nightly-check"),
        _observation(ObservationKind.RECOVERY_PROOF, "restore-proof"),
        _observation(ObservationKind.HEALTH_CHECK, "doctor-check"),
    )

    results = assess_significant_families(_catalogue(*reversed(families)), fingerprint)

    assert tuple(item.family_id for item in results) == tuple(
        sorted(family["family_id"] for family in families)
    )
    assert all(item.matched_components for item in results)


def test_manual_only_is_visible_as_not_assessed_even_when_names_match() -> None:
    family = _family(
        "private-feedback",
        profile=None,
        members=["workflow-skill"],
        components=[{"component_type": "capability", "capability_id": "workflow-skill"}],
    )
    result = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.SKILL, "workflow-skill")),
    )[0]

    assert result.disposition is FamilyAssessmentDisposition.NOT_ASSESSED
    assert result.matched_components == ()
    assert result.unresolved_components == ("capability:workflow-skill",)
    assert result.recommendable_member_ids == ("workflow-skill",)
    assert "person must decide" in result.reason


def test_dormant_and_parked_members_are_never_recommendable() -> None:
    family = _family(
        "inactive-family",
        profile="catalogue",
        members=["dormant-helper", "parked-engine"],
        components=[
            {"component_type": "capability", "capability_id": "dormant-helper"},
            {"component_type": "capability", "capability_id": "parked-engine"},
        ],
    )
    result = assess_significant_families(
        _catalogue(family),
        _fingerprint(_observation(ObservationKind.SKILL, "dormant-helper")),
    )[0]

    assert result.signed_availability.value == "unavailable"
    assert result.recommendable_member_ids == ()
    assert result.disposition is FamilyAssessmentDisposition.NOT_RECOMMENDABLE


def test_evidence_references_and_observations_are_sorted_and_deduplicated() -> None:
    family = _family(
        "workflow",
        profile="catalogue",
        members=["workflow-skill"],
        components=[{"component_type": "capability", "capability_id": "workflow-skill"}],
    )
    observations = (
        _observation(
            ObservationKind.SKILL,
            "workflow-alias",
            reference="fixture:z",
        ),
        _observation(
            ObservationKind.SKILL,
            "workflow-skill",
            reference="fixture:a",
        ),
    )
    result = assess_significant_families(_catalogue(family), _fingerprint(*reversed(observations)))[
        0
    ]

    assert result.evidence_references == ("fixture:a", "fixture:z")
    assert result.matched_observation_ids == tuple(
        sorted(item.observation_id for item in observations)
    )
    assert result.matched_components[0].observation_ids == result.matched_observation_ids


def test_unknown_automatic_profile_aborts_without_partial_assessments() -> None:
    valid_family = _catalogue(
        _family(
            "workflow",
            profile="catalogue",
            members=["workflow-skill"],
            components=[{"component_type": "capability", "capability_id": "workflow-skill"}],
        )
    ).capability_families[0]
    unsafe_assessment = AutomaticAssessmentV2.model_construct(
        mode="automatic", profile="unreviewed-profile"
    )
    family_values = {
        field_name: getattr(valid_family, field_name)
        for field_name in type(valid_family).model_fields
    }
    family_values["assessment"] = unsafe_assessment
    unsafe_family = CapabilityFamilyV2.model_construct(**family_values)
    base_catalogue = _catalogue()
    catalogue_values = {
        field_name: getattr(base_catalogue, field_name)
        for field_name in type(base_catalogue).model_fields
    }
    catalogue_values["capability_families"] = (unsafe_family,)
    unsafe_catalogue = CatalogueV2.model_construct(**catalogue_values)

    with pytest.raises(UnsupportedAssessmentProfileError, match="unreviewed-profile"):
        assess_significant_families(unsafe_catalogue, _fingerprint())
