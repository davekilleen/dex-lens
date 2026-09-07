"""The 0.1.9 enriched four-class catalogue contract, end to end.

This file is the executable form of the cross-repo schema delta Dex Core
handed to Lens: the rollout-compatible union must accept both the currently
published skill-only catalogue and the four class-discriminated enriched
shapes, the exported schema must state the same contract as five closed
branches, and every consumer safeguard — dormant and parked entries never
offered as active, skill logic applied only to skills — must hold through
signature verification, schema validation, cache round-trip and ranking.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError
from tests.diagnosis.conftest import contract, presence_only_envelope

from capability_exchange.catalogue.agent import render_catalogue_digest
from capability_exchange.catalogue.bridge import (
    rank_capability_shelf,
    render_portable_brief_markdown,
)
from capability_exchange.catalogue.schema_contract import (
    MINIMUM_LENS_VERSION,
    MINIMUM_VERSION_KEYWORD,
    SIGNIFICANT_FAMILY_MINIMUM_LENS_VERSION,
    build_catalogue_schema,
    iter_catalogue_schema_errors,
)
from capability_exchange.catalogue.v2 import (
    ActiveSkillCapabilityEntryV2,
    CatalogueCapabilityEntryV2,
    CatalogueVerificationError,
    KeyRing,
    LegacySkillCapabilityEntryV2,
    McpServerCapabilityEntryV2,
    ScheduledAutomationCapabilityEntryV2,
    SystemEngineCapabilityEntryV2,
    VerifiedCatalogueStore,
    canonical_signed_payload,
    capability_is_active,
    verify_catalogue_envelope,
)
from capability_exchange.diagnosis import assess

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)

_ENTRY_ADAPTER: TypeAdapter = TypeAdapter(CatalogueCapabilityEntryV2)

_RELEASED_018_SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "catalogue"
    / "dex-lens-catalogue-v2.schema.v0.1.8.json"
)


@pytest.fixture()
def signing_key() -> Ed25519PrivateKey:
    seed = b"dex-lens-catalogue-v2-test-key!!"
    assert len(seed) == 32
    return Ed25519PrivateKey.from_private_bytes(seed)


@pytest.fixture()
def keyring(signing_key: Ed25519PrivateKey) -> KeyRing:
    public_key = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return KeyRing({"dex-core-2026-08-test": base64.b64encode(public_key).decode("ascii")})


def _jobs_taxonomy() -> list[dict[str, object]]:
    return [
        {
            "job_id": "plan-my-work",
            "label": "Plan my work",
            "description": "Choose a realistic plan from current commitments.",
            "confirmed_gap_signals": ["no recent real example demonstrates this outcome"],
        },
        {
            "job_id": "maintain-context",
            "label": "Maintain context",
            "description": "Keep useful context durable.",
            "confirmed_gap_signals": ["the system forgets decisions"],
        },
    ]


def _evidence() -> list[dict[str, str]]:
    return [
        {
            "level": "supported",
            "source": "Dex release evidence",
            "summary": "The capability ships in the named Dex release.",
            "limitations": "Lens has not inspected this user's system.",
        }
    ]


def _common(capability_id: str, title: str) -> dict[str, object]:
    return {
        "capability_id": capability_id,
        "title": title,
        "summary": f"{title} does one useful thing.",
        "value": f"{title} is worth having.",
        "jobs": ["plan-my-work"],
        "prerequisites": ["a running Dex install"],
        "trade_offs": ["only as good as its inputs"],
        "evidence": _evidence(),
        "release_provenance": "core-release",
    }


def _skill_fields() -> dict[str, object]:
    return {
        "compatibility": {
            "host_adapters": ["claude-code"],
            "foundation_capabilities": ["durable-memory-provenance"],
            "minimum_lens_contract": "0.1.0",
            "platforms": ["macos"],
            "needs_hooks": False,
            "needs_mcp": True,
            "host_requirements": ["skills-directory"],
            "limitations": ["Brief only; Lens does not apply changes."],
        },
        "docs_url": "https://github.com/davekilleen/Dex",
        "since_release": "1.90.0",
        "changed_in": [],
        "portable_brief": {
            "goal": "adapt the pattern locally",
            "method_outline": ["read the confirmed source"],
            "verification_checklist": ["the person can preview the outcome"],
            "rollback_advice": "remove the local note",
            "safety_notes": ["reads only"],
        },
    }


def legacy_skill(capability_id: str = "legacy-skill", title: str = "Legacy Skill") -> dict:
    return {**_common(capability_id, title), **_skill_fields()}


def enriched_skill(
    capability_id: str = "enriched-skill",
    title: str = "Enriched Skill",
    *,
    availability: str = "active",
    impact_tier: str = "high",
) -> dict:
    return {
        **_common(capability_id, title),
        **_skill_fields(),
        "capability_class": "active-skill",
        "impact_tier": impact_tier,
        "availability": availability,
    }


def mcp_server(capability_id: str = "dex-work-mcp", title: str = "Work MCP server") -> dict:
    return {
        **_common(capability_id, title),
        "capability_class": "mcp-server",
        "impact_tier": "core",
        "availability": "active",
        "server_name": "dex-work",
        "tool_count": 12,
        "example_tools": ["list_tasks", "add_note"],
        "source_paths": ["core/mcp/work/server.py", "core/mcp/work/tools.py"],
    }


def scheduled_automation(
    capability_id: str = "dex-meeting-intel", title: str = "Meeting Intel"
) -> dict:
    return {
        **_common(capability_id, title),
        "capability_class": "scheduled-automation",
        "impact_tier": "medium",
        "availability": "active",
        "automation_label": "com.dex.meeting-intel",
        "cadence": "weekdays at 07:30",
        "source_paths": ["core/automations/meeting_intel.py"],
        "installer_path": "core/automations/install_meeting_intel.sh",
        "program_target": "core/automations/meeting_intel.py --daily {DEX_HOME}",
        "run_at_load": False,
    }


def system_engine(
    capability_id: str = "ritual-intelligence-engine",
    title: str = "Ritual Intelligence Engine",
    *,
    availability: str = "parked",
) -> dict:
    return {
        **_common(capability_id, title),
        "capability_class": "system-engine",
        "impact_tier": "niche",
        "availability": availability,
        "source_paths": ["core/engines/ritual/a.py", "core/engines/ritual/b.py"],
        "component_count": 2,
        "example_components": ["core/engines/ritual/a.py"],
    }


def envelope_for(capabilities: list[dict], version: int = 7) -> dict:
    return {
        "metadata": {
            "contract_version": "dex-lens-catalogue-v2",
            "catalog_version": version,
            "produced_at": NOW.isoformat().replace("+00:00", "Z"),
            "expires_at": (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
            "producer": "Dex Core release pipeline",
            "core_release": "v1.97.0",
            "key_id": "dex-core-2026-08-test",
        },
        "catalogue": {
            "jobs_taxonomy": _jobs_taxonomy(),
            "capabilities": capabilities,
            "portable_brief": {
                "format": "markdown",
                "audience": "the person's own AI system",
                "safety_boundary": "Brief only; no automatic Adaptation.",
            },
        },
    }


def sign_envelope(envelope: dict, signing_key: Ed25519PrivateKey) -> str:
    signature = signing_key.sign(canonical_signed_payload(envelope))
    signed = dict(envelope)
    signed["signature"] = base64.b64encode(signature).decode("ascii")
    return json.dumps(signed, sort_keys=True, separators=(",", ":"))


def _mixed_capabilities() -> list[dict]:
    return [
        legacy_skill(),
        enriched_skill(),
        enriched_skill("dormant-skill", "Dormant Skill", availability="dormant"),
        mcp_server(),
        scheduled_automation(),
        system_engine("active-engine", "Active Engine", availability="active"),
        system_engine(),
    ]


# ---------------------------------------------------------------------------
# Positive contract tests
# ---------------------------------------------------------------------------


def test_the_currently_published_legacy_skill_only_envelope_still_verifies(
    signing_key: Ed25519PrivateKey, keyring: KeyRing
) -> None:
    """Contract positive 1: the live catalogue shape — skill-only entries with
    none of the class fields — verifies unchanged through the 0.1.9 union."""
    raw = sign_envelope(envelope_for([legacy_skill()]), signing_key)
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)
    (entry,) = verified.catalogue.capabilities
    assert type(entry) is LegacySkillCapabilityEntryV2
    assert capability_is_active(entry)
    assert not list(iter_catalogue_schema_errors(json.loads(raw)))


def test_one_enriched_active_skill(signing_key: Ed25519PrivateKey, keyring: KeyRing) -> None:
    raw = sign_envelope(envelope_for([enriched_skill()]), signing_key)
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)
    (entry,) = verified.catalogue.capabilities
    assert type(entry) is ActiveSkillCapabilityEntryV2
    assert entry.impact_tier == "high"
    assert entry.availability == "active"
    assert entry.portable_brief.goal == "adapt the pattern locally"
    assert not list(iter_catalogue_schema_errors(json.loads(raw)))


def test_a_dormant_skill_validates_but_is_never_offered_as_active(
    signing_key: Ed25519PrivateKey, keyring: KeyRing
) -> None:
    raw = sign_envelope(
        envelope_for([enriched_skill("dormant-skill", availability="dormant")]), signing_key
    )
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)
    (entry,) = verified.catalogue.capabilities
    assert entry.availability == "dormant"
    assert not capability_is_active(entry)

    capability_map = assess([contract("weekly-report")], presence_only_envelope())
    shelf = rank_capability_shelf(
        verified.catalogue,
        capability_map,
        host_adapter="claude-code",
        lens_contract_version="0.1.9",
    )
    (match,) = shelf
    assert match.shelf_section == "browse"
    assert match.availability == "dormant"
    assert "never offered as an active match" in match.match_explanation
    # The explanation never contradicts itself: a non-active entry with
    # foundation matches must not also read "picked because".
    assert "picked because" not in match.match_explanation

    # The bridge portable brief (used by the concierge journey for any shelf
    # selection) carries the same not-on-offer framing the agent brief does.
    rendered = render_portable_brief_markdown(
        verified.catalogue,
        capability_map,
        shelf,
        selected_capability_id="dormant-skill",
        selected_job_id="weekly-report",
    )
    assert "**dormant**" in rendered
    assert "not currently on offer" in rendered


def test_one_mcp_server_with_tool_count_and_example_tools(
    signing_key: Ed25519PrivateKey, keyring: KeyRing
) -> None:
    raw = sign_envelope(envelope_for([mcp_server()]), signing_key)
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)
    (entry,) = verified.catalogue.capabilities
    assert type(entry) is McpServerCapabilityEntryV2
    assert entry.server_name == "dex-work"
    assert entry.tool_count == 12
    assert entry.example_tools == ("list_tasks", "add_note")
    assert not list(iter_catalogue_schema_errors(json.loads(raw)))


def test_one_scheduled_automation_with_cadence_and_launchd_label(
    signing_key: Ed25519PrivateKey, keyring: KeyRing
) -> None:
    raw = sign_envelope(envelope_for([scheduled_automation()]), signing_key)
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)
    (entry,) = verified.catalogue.capabilities
    assert type(entry) is ScheduledAutomationCapabilityEntryV2
    # The catalogue id stays kebab-case; the launchd label lives apart.
    assert entry.capability_id == "dex-meeting-intel"
    assert entry.automation_label == "com.dex.meeting-intel"
    assert entry.cadence == "weekdays at 07:30"
    assert entry.run_at_load is False
    assert not list(iter_catalogue_schema_errors(json.loads(raw)))


def test_one_active_system_engine(signing_key: Ed25519PrivateKey, keyring: KeyRing) -> None:
    raw = sign_envelope(
        envelope_for([system_engine("active-engine", availability="active")]), signing_key
    )
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)
    (entry,) = verified.catalogue.capabilities
    assert type(entry) is SystemEngineCapabilityEntryV2
    assert entry.component_count == 2
    assert capability_is_active(entry)
    assert not list(iter_catalogue_schema_errors(json.loads(raw)))


def test_a_parked_system_engine_validates_but_is_never_recommended(
    signing_key: Ed25519PrivateKey, keyring: KeyRing
) -> None:
    raw = sign_envelope(envelope_for([system_engine()]), signing_key)
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)
    (entry,) = verified.catalogue.capabilities
    assert entry.availability == "parked"
    assert not capability_is_active(entry)

    capability_map = assess([contract("weekly-report")], presence_only_envelope())
    shelf = rank_capability_shelf(
        verified.catalogue,
        capability_map,
        host_adapter="claude-code",
        lens_contract_version="0.1.9",
    )
    (match,) = shelf
    assert match.shelf_section == "browse"
    assert match.availability == "parked"
    assert "never offered as an active match" in match.match_explanation
    # The digest names the parked state so a person never reads it as on offer.
    digest = render_catalogue_digest(verified.catalogue)
    assert "parked" in digest


def test_mixed_four_class_signed_envelope_through_the_whole_pipeline(
    signing_key: Ed25519PrivateKey, keyring: KeyRing, tmp_path: Path
) -> None:
    """Contract positive 8: model validation, schema validation, signature
    verification, cache round-trip, and ranking ingestion over one envelope
    carrying all five shapes."""
    raw = sign_envelope(envelope_for(_mixed_capabilities(), version=9), signing_key)

    # Schema validation of the raw document, through the exported contract.
    assert not list(iter_catalogue_schema_errors(json.loads(raw)))

    # Signature verification, then model validation via the union.
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)
    types = [type(entry).__name__ for entry in verified.catalogue.capabilities]
    assert types == [
        "LegacySkillCapabilityEntryV2",
        "ActiveSkillCapabilityEntryV2",
        "ActiveSkillCapabilityEntryV2",
        "McpServerCapabilityEntryV2",
        "ScheduledAutomationCapabilityEntryV2",
        "SystemEngineCapabilityEntryV2",
        "SystemEngineCapabilityEntryV2",
    ]

    # Cache round-trip re-verifies the exact signed bytes and keeps the
    # discriminator and class fields intact.
    store = VerifiedCatalogueStore(tmp_path)
    store.save_verified(verified)
    reloaded = verify_catalogue_envelope(
        json.loads((tmp_path / "lens-catalogue-v2-cache.json").read_text())[
            "verified_envelope_json"
        ],
        keyring=keyring,
        now=NOW,
    )
    reloaded_via_store = store.load_last_verified(keyring=keyring, now=NOW)
    for envelope in (reloaded, reloaded_via_store):
        classes = [type(entry).__name__ for entry in envelope.catalogue.capabilities]
        assert classes == types
        mcp = envelope.catalogue.capabilities[3]
        assert mcp.server_name == "dex-work" and mcp.tool_count == 12

    # Ranking ingestion: every entry ranks; nothing dormant or parked is
    # offered as an active match.
    capability_map = assess([contract("weekly-report")], presence_only_envelope())
    shelf = rank_capability_shelf(
        verified.catalogue,
        capability_map,
        host_adapter="claude-code",
        lens_contract_version="0.1.9",
    )
    assert len(shelf) == len(verified.catalogue.capabilities)
    offered_as_active = {
        match.capability_id for match in shelf if match.shelf_section == "picked"
    }
    assert "dormant-skill" not in offered_as_active
    assert "ritual-intelligence-engine" not in offered_as_active
    by_id = {match.capability_id: match for match in shelf}
    assert by_id["dex-work-mcp"].capability_class == "mcp-server"
    assert "12 tool(s)" in by_id["dex-work-mcp"].compatibility_explanation
    assert "weekdays at 07:30" in by_id["dex-meeting-intel"].compatibility_explanation
    assert "2 component(s)" in by_id["active-engine"].compatibility_explanation


def test_exported_schema_declares_the_five_branch_contract() -> None:
    schema = build_catalogue_schema()
    assert MINIMUM_LENS_VERSION == "0.1.9"
    assert (
        schema[MINIMUM_VERSION_KEYWORD]
        == SIGNIFICANT_FAMILY_MINIMUM_LENS_VERSION
        == "0.1.16"
    )
    union = schema["$defs"]["CatalogueCapabilityEntryV2"]
    assert [ref["$ref"].rsplit("/", 1)[1] for ref in union["oneOf"]] == [
        "LegacySkillCapabilityEntryV2",
        "ActiveSkillCapabilityEntryV2",
        "McpServerCapabilityEntryV2",
        "ScheduledAutomationCapabilityEntryV2",
        "SystemEngineCapabilityEntryV2",
    ]
    for name in [ref["$ref"].rsplit("/", 1)[1] for ref in union["oneOf"]]:
        branch = schema["$defs"][name]
        assert branch["additionalProperties"] is False, name
    assert schema["$defs"]["CatalogueV2"]["properties"]["capabilities"]["items"] == {
        "$ref": "#/$defs/CatalogueCapabilityEntryV2"
    }
    # The published envelope still requires a non-empty signature.
    assert "signature" in schema["required"]
    assert schema["properties"]["signature"]["minLength"] == 1


# ---------------------------------------------------------------------------
# Negative contract tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder", [enriched_skill, mcp_server, scheduled_automation, system_engine]
)
def test_missing_capability_class_is_refused_on_every_non_legacy_shape(builder) -> None:
    entry = builder()
    del entry["capability_class"]
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(entry)


@pytest.mark.parametrize(
    "builder", [enriched_skill, mcp_server, scheduled_automation, system_engine]
)
def test_unknown_capability_class_is_refused(builder) -> None:
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python({**builder(), "capability_class": "sidecar"})


@pytest.mark.parametrize(
    ("field", "value"),
    [("impact_tier", "legendary"), ("availability", "sometimes")],
)
def test_unknown_impact_tier_or_availability_is_refused(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python({**mcp_server(), field: value})


@pytest.mark.parametrize(
    ("builder", "availability"),
    [
        (mcp_server, "dormant"),
        (mcp_server, "parked"),
        (scheduled_automation, "dormant"),
        (scheduled_automation, "parked"),
        (enriched_skill, "parked"),
        (system_engine, "dormant"),
    ],
)
def test_availability_is_restricted_further_by_class(builder, availability: str) -> None:
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python({**builder(), "availability": availability})


@pytest.mark.parametrize("builder", [mcp_server, scheduled_automation, system_engine])
@pytest.mark.parametrize(
    "field", ["compatibility", "docs_url", "since_release", "changed_in", "portable_brief"]
)
def test_skill_only_fields_are_refused_on_every_non_skill_class(builder, field: str) -> None:
    entry = {**builder(), field: legacy_skill()[field]}
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(entry)


@pytest.mark.parametrize(
    ("builder", "field"),
    [
        (mcp_server, "server_name"),
        (mcp_server, "tool_count"),
        (mcp_server, "example_tools"),
        (mcp_server, "source_paths"),
        (scheduled_automation, "automation_label"),
        (scheduled_automation, "cadence"),
        (scheduled_automation, "source_paths"),
        (scheduled_automation, "installer_path"),
        (scheduled_automation, "program_target"),
        (scheduled_automation, "run_at_load"),
        (system_engine, "source_paths"),
        (system_engine, "component_count"),
        (system_engine, "example_components"),
        (enriched_skill, "impact_tier"),
        (enriched_skill, "availability"),
        (enriched_skill, "portable_brief"),
    ],
)
def test_missing_class_specific_required_fields_are_refused(builder, field: str) -> None:
    entry = builder()
    del entry[field]
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(entry)


def test_dotted_capability_ids_are_refused_the_label_belongs_in_automation_label() -> None:
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(
            {**scheduled_automation(), "capability_id": "com.dex.meeting-intel"}
        )
    # And the automation label may not be plain kebab-case either way around.
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(
            {**scheduled_automation(), "automation_label": "dex-meeting-intel"}
        )


def test_duplicate_capability_ids_across_different_classes_are_refused(
    signing_key: Ed25519PrivateKey, keyring: KeyRing
) -> None:
    envelope = envelope_for(
        [legacy_skill("shared-id"), mcp_server("shared-id")],
    )
    with pytest.raises(CatalogueVerificationError, match="schema"):
        verify_catalogue_envelope(sign_envelope(envelope, signing_key), keyring=keyring, now=NOW)
    instance = dict(envelope)
    instance["signature"] = "schema-only-placeholder"
    errors = list(iter_catalogue_schema_errors(instance))
    assert any("capability_id" in error.message for error in errors), errors


def test_unknown_job_references_are_refused_on_enriched_entries(
    signing_key: Ed25519PrivateKey, keyring: KeyRing
) -> None:
    envelope = envelope_for([{**mcp_server(), "jobs": ["job-nobody-published"]}])
    with pytest.raises(CatalogueVerificationError, match="schema"):
        verify_catalogue_envelope(sign_envelope(envelope, signing_key), keyring=keyring, now=NOW)


def test_engine_component_count_must_match_source_paths() -> None:
    with pytest.raises(ValidationError, match="component_count"):
        _ENTRY_ADAPTER.validate_python({**system_engine(), "component_count": 3})


def test_engine_example_components_must_come_from_source_paths() -> None:
    with pytest.raises(ValidationError, match="example_components"):
        _ENTRY_ADAPTER.validate_python(
            {**system_engine(), "example_components": ["core/engines/other/x.py"]}
        )


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../outside.py", "core/../../outside.py", ".."]
)
def test_unsafe_source_paths_are_refused(path: str) -> None:
    with pytest.raises(ValidationError):
        _ENTRY_ADAPTER.validate_python(
            {**system_engine(), "source_paths": [path], "component_count": 1,
             "example_components": [path]}
        )


def test_the_released_018_schema_rejects_the_enriched_shapes() -> None:
    """The compatibility boundary, documented: the schema v0.1.8 shipped
    requires skill fields on every entry, so an enriched non-skill entry
    fails against it and Core must not sign enriched output before 0.1.9."""
    released = json.loads(_RELEASED_018_SCHEMA.read_text(encoding="utf-8"))
    assert MINIMUM_VERSION_KEYWORD not in released
    instance = envelope_for(_mixed_capabilities())
    instance["signature"] = "schema-only-placeholder"
    # Structural validation only: the 0.1.8 dialect keyword is Lens's own, so
    # a vanilla Draft 2020-12 check of the released structure is the honest
    # comparison here.
    validator = Draft202012Validator(
        {key: value for key, value in released.items() if key != "$schema"}
    )
    errors = list(validator.iter_errors(instance))
    assert errors, "the 0.1.8 schema unexpectedly accepts enriched entries"
    # The same instance is clean against the 0.1.9 contract.
    assert not list(iter_catalogue_schema_errors(instance))


def test_enriched_envelope_fail_closed_cases_remain_fail_closed(
    signing_key: Ed25519PrivateKey, keyring: KeyRing, tmp_path: Path
) -> None:
    """Invalid signature, unknown key, expiry, rollback, and cache tamper all
    still refuse an enriched catalogue outright."""
    envelope = envelope_for(_mixed_capabilities(), version=9)
    raw = sign_envelope(envelope, signing_key)

    tampered = json.loads(raw)
    tampered["catalogue"]["capabilities"][3]["tool_count"] = 13
    with pytest.raises(CatalogueVerificationError, match="signature"):
        verify_catalogue_envelope(
            json.dumps(tampered, sort_keys=True, separators=(",", ":")),
            keyring=keyring,
            now=NOW,
        )

    unknown_key = envelope_for(_mixed_capabilities(), version=9)
    unknown_key["metadata"]["key_id"] = "unknown-key"
    with pytest.raises(CatalogueVerificationError, match="key_id"):
        verify_catalogue_envelope(
            sign_envelope(unknown_key, signing_key), keyring=keyring, now=NOW
        )

    with pytest.raises(CatalogueVerificationError, match="expired"):
        verify_catalogue_envelope(raw, keyring=keyring, now=NOW + timedelta(days=31))

    with pytest.raises(CatalogueVerificationError, match="rollback"):
        verify_catalogue_envelope(
            sign_envelope(envelope_for(_mixed_capabilities(), version=8), signing_key),
            keyring=keyring,
            now=NOW,
            highest_verified_catalog_version=9,
        )

    store = VerifiedCatalogueStore(tmp_path)
    store.save_verified(verify_catalogue_envelope(raw, keyring=keyring, now=NOW))
    cache_path = tmp_path / "lens-catalogue-v2-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cached_envelope = json.loads(cache["verified_envelope_json"])
    cached_envelope["catalogue"]["capabilities"][3]["server_name"] = "dex-evil"
    cache["verified_envelope_json"] = json.dumps(
        cached_envelope, sort_keys=True, separators=(",", ":")
    )
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    with pytest.raises(CatalogueVerificationError, match="signature"):
        store.load_last_verified(keyring=keyring, now=NOW)


def test_the_unsigned_preview_sentinel_never_passes_verification(
    keyring: KeyRing,
) -> None:
    """Core's committed preview carries an obvious sentinel in place of a
    signature; it must never pass Lens cryptographic verification."""
    envelope = envelope_for(_mixed_capabilities())
    envelope["signature"] = "UNSIGNED-PREVIEW-NOT-FOR-PUBLICATION"
    with pytest.raises(CatalogueVerificationError, match="base64"):
        verify_catalogue_envelope(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")),
            keyring=keyring,
            now=NOW,
        )
