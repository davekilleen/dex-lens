"""Whole-system discovery from one immutable, already-redacted snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.adapters.claude_code.discovery import discover_fingerprint
from capability_exchange.adapters.claude_code.live_state import LiveState
from capability_exchange.adapters.claude_code.snapshot import InspectionSnapshot, take_snapshot
from capability_exchange.concierge.collection import ScopeSnapshot
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    ObservationKind,
    OperationalState,
)

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def _snapshot(root: Path) -> InspectionSnapshot:
    contract = claude_code_contract((str(root.resolve()),))
    allowlist = CanonicalAllowlist(contract.read_scope, denied_paths=contract.denied_paths)
    return take_snapshot(allowlist, taken_at=NOW)


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _synthetic_legacy_system(root: Path) -> InspectionSnapshot:
    root.mkdir()
    _write(root, "VERSION", "v0.8.3\n")
    _write(
        root,
        ".claude/skills/daily-plan/SKILL.md",
        "---\nname: daily-plan\ndescription: Make a grounded daily plan.\n---\n",
    )
    _write(
        root,
        ".mcp.json",
        json.dumps(
            {
                "mcpServers": {
                    "career-data": {
                        "command": "career-server",
                        "env": {"API_TOKEN": "not-retained"},
                    }
                }
            }
        ),
    )
    _write(
        root,
        ".claude/settings.json",
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [{"matcher": "Write", "hooks": [{"command": "private-runner"}]}]
                }
            }
        ),
    )
    _write(
        root,
        "System/integrations/registry.json",
        json.dumps({"providers": {"calendar": {}, "crm": {}, "documents": {}}}),
    )
    _write(
        root,
        "Library/LaunchAgents/nightly-check.plist",
        "<plist><dict><key>Label</key><string>nightly-check</string>"
        "<key>StartCalendarInterval</key><dict/></dict></plist>",
    )
    _write(root, "scripts/system-doctor.py", "# local health check\n")
    _write(root, "checks/restore-proof.json", '{"status": "passed"}\n')
    return _snapshot(root)


def test_discovers_whole_system_without_equating_presence_with_working(tmp_path: Path) -> None:
    fingerprint = discover_fingerprint(
        _synthetic_legacy_system(tmp_path / "legacy-system"),
        collected_at=NOW,
    )
    by_key = {(item.kind, item.identity): item for item in fingerprint.observations}

    release = by_key[(ObservationKind.RELEASE, "dex-core")]
    assert release.attributes[0].value == "v0.8.3"
    assert (
        by_key[(ObservationKind.MCP_SERVER, "career-data")].operational_state
        is OperationalState.DECLARED
    )
    assert (
        by_key[(ObservationKind.AUTOMATION, "nightly-check")].operational_state
        is OperationalState.IMPLEMENTED
    )
    assert (
        by_key[(ObservationKind.HEALTH_CHECK, "system-doctor")].operational_state
        is OperationalState.IMPLEMENTED
    )
    assert (
        by_key[(ObservationKind.INTEGRATION_REGISTRY, "local-integrations")].operational_state
        is OperationalState.IMPLEMENTED
    )
    assert (ObservationKind.MCP_TOOL, "career-data:unknown") not in by_key


def test_mcp_and_hook_discovery_never_retains_secret_values(tmp_path: Path) -> None:
    canary = "DEX_LENS_CANARY_DO_NOT_RETAIN"
    root = tmp_path / "secret-bearing-system"
    root.mkdir()
    _write(
        root,
        ".mcp.json",
        json.dumps(
            {
                "mcpServers": {
                    "career-data": {
                        "command": "runner",
                        "env": {"API_TOKEN": canary},
                    }
                }
            }
        ),
    )
    _write(
        root,
        ".claude/settings.json",
        json.dumps(
            {"hooks": {"PostToolUse": [{"hooks": [{"command": f"runner --token {canary}"}]}]}}
        ),
    )

    rendered = discover_fingerprint(_snapshot(root), collected_at=NOW).model_dump_json()

    assert canary not in rendered
    assert "API_TOKEN" not in rendered
    assert "--token" not in rendered


def test_discovers_per_server_and_direct_map_mcp_manifests_without_secrets(
    tmp_path: Path,
) -> None:
    canary = "DEX_LENS_MCP_MANIFEST_CANARY"
    root = tmp_path / "manifest-system"
    root.mkdir()
    _write(
        root,
        ".claude/mcp/career.json",
        json.dumps(
            {
                "name": "career",
                "description": "Career evidence tools",
                "server": {
                    "command": "python",
                    "args": ["private-server.py"],
                    "env": {"API_TOKEN": canary},
                },
            }
        ),
    )
    _write(
        root,
        ".claude/mcp-servers.json",
        json.dumps(
            {
                "dev-browser": {
                    "command": "browser-runner",
                    "args": ["--credential", canary],
                }
            }
        ),
    )

    fingerprint = discover_fingerprint(_snapshot(root), collected_at=NOW)
    servers = {
        item.identity: item
        for item in fingerprint.observations
        if item.kind is ObservationKind.MCP_SERVER
    }

    assert set(servers) == {"career", "dev-browser"}
    assert all(
        item.configuration_state is ConfigurationState.DECLARED
        for item in servers.values()
    )
    rendered = fingerprint.model_dump_json()
    assert canary not in rendered
    assert "private-server.py" not in rendered


def test_provider_identities_reject_every_canonical_secret_marker(tmp_path: Path) -> None:
    root = tmp_path / "provider-registry"
    root.mkdir()
    rejected = {
        "api_key",
        "calendar-api-key",
        "auth",
        "private-key",
        "passwd",
        "access-token",
    }
    _write(
        root,
        "System/integrations/registry.json",
        json.dumps({"providers": {"calendar": {}, **dict.fromkeys(rejected, {})}}),
    )

    fingerprint = discover_fingerprint(_snapshot(root), collected_at=NOW)
    provider_ids = {
        item.identity
        for item in fingerprint.observations
        if item.kind is ObservationKind.INTEGRATION_PROVIDER
    }
    registry = next(
        item
        for item in fingerprint.observations
        if item.kind is ObservationKind.INTEGRATION_REGISTRY
    )

    assert provider_ids == {"calendar"}
    assert rejected.isdisjoint(provider_ids)
    assert next(item.value for item in registry.attributes if item.key == "provider-count") == "1"


def test_exact_duplicate_declarations_are_folded(tmp_path: Path) -> None:
    root = tmp_path / "duplicate-system"
    root.mkdir()
    declaration = json.dumps({"mcpServers": {"career-data": {"command": "runner"}}})
    _write(root, ".mcp.json", declaration)
    _write(root, ".claude/settings.json", declaration)

    fingerprint = discover_fingerprint(_snapshot(root), collected_at=NOW)

    matching = [
        item
        for item in fingerprint.observations
        if item.kind is ObservationKind.MCP_SERVER and item.identity == "career-data"
    ]
    assert len(matching) == 1


def test_same_named_skills_from_distinct_approved_sources_emit_separately(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    global_home = tmp_path / "global"
    for root in (vault, global_home):
        (root / "planner").mkdir(parents=True)
        (root / "planner" / "SKILL.md").write_text("# Planner\n")
    consent = ScopeSnapshot.capture(
        (vault, global_home),
        source_descriptors=(
            {
                "canonical_root": vault.resolve(),
                "source_id": "scope:vault",
                "source_class": "vault-authored",
                "scope_reference": "scope:sha256:" + "a" * 64,
            },
            {
                "canonical_root": global_home.resolve(),
                "source_id": "scope:global",
                "source_class": "user-global",
                "scope_reference": "scope:sha256:" + "b" * 64,
            },
        ),
    )
    snapshot = take_snapshot(
        CanonicalAllowlist((vault, global_home)),
        source_descriptors=consent.source_descriptors,
        taken_at=NOW,
    )

    fingerprint = discover_fingerprint(snapshot, collected_at=NOW)
    matching = [
        item
        for item in fingerprint.observations
        if item.kind is ObservationKind.SKILL and item.identity == "planner"
    ]

    assert [item.provenance.source_id for item in matching] == [
        "scope:global",
        "scope:vault",
    ]


def test_unsourced_live_state_cannot_upgrade_same_automation_across_sources(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    global_home = tmp_path / "global"
    plist = (
        "<plist><dict><key>Label</key><string>nightly-check</string>"
        "<key>StartCalendarInterval</key><dict/></dict></plist>"
    )
    for root in (vault, global_home):
        root.mkdir()
        _write(root, "Library/LaunchAgents/nightly-check.plist", plist)
    consent = ScopeSnapshot.capture(
        (vault, global_home),
        source_descriptors=(
            {
                "canonical_root": vault.resolve(),
                "source_id": "scope:vault",
                "source_class": "vault-authored",
                "scope_reference": "scope:sha256:" + "a" * 64,
            },
            {
                "canonical_root": global_home.resolve(),
                "source_id": "scope:global",
                "source_class": "user-global",
                "scope_reference": "scope:sha256:" + "b" * 64,
            },
        ),
    )
    snapshot = take_snapshot(
        CanonicalAllowlist((vault, global_home)),
        source_descriptors=consent.source_descriptors,
        taken_at=NOW,
    )

    fingerprint = discover_fingerprint(
        snapshot,
        collected_at=NOW,
        live_states=(
            LiveState(
                kind="automation",
                identity="nightly-check",
                operational_state=OperationalState.LOADED,
                captured_at=NOW,
            ),
        ),
    )
    matching = [
        item
        for item in fingerprint.observations
        if item.kind is ObservationKind.AUTOMATION and item.identity == "nightly-check"
    ]

    assert len(matching) == 2
    assert {item.operational_state for item in matching} == {OperationalState.NOT_ASSESSED}
    assert all(
        any(
            attribute.key == "live-state-match"
            and attribute.value == "ambiguous-across-approved-sources"
            for attribute in item.attributes
        )
        for item in matching
    )


def test_explicit_working_copy_source_cannot_prove_active_capability(tmp_path: Path) -> None:
    root = tmp_path / "ordinary-name"
    (root / "planner").mkdir(parents=True)
    (root / "planner" / "SKILL.md").write_text("# Planner\n")
    consent = ScopeSnapshot.capture(
        (root,),
        source_descriptors=(
            {
                "canonical_root": root.resolve(),
                "source_id": "scope:working-copy",
                "source_class": "working-copy",
                "scope_reference": "scope:sha256:" + "c" * 64,
            },
        ),
    )
    snapshot = take_snapshot(
        CanonicalAllowlist((root,)),
        source_descriptors=consent.source_descriptors,
        taken_at=NOW,
    )

    matching = [
        item
        for item in discover_fingerprint(snapshot, collected_at=NOW).observations
        if item.kind is ObservationKind.SKILL and item.identity == "planner"
    ]

    assert len(matching) == 1
    assert matching[0].provenance.source_class.value == "working-copy"
    assert matching[0].operational_state is OperationalState.NOT_ASSESSED


def test_discovery_does_not_accept_a_post_capture_provenance_override(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    root.mkdir()

    with pytest.raises(TypeError):
        discover_fingerprint(
            _snapshot(root),
            collected_at=NOW,
            source_descriptors=(),  # type: ignore[call-arg]
        )
