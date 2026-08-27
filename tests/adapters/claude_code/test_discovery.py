"""Whole-system discovery from one immutable, already-redacted snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.adapters.claude_code.discovery import discover_fingerprint
from capability_exchange.adapters.claude_code.snapshot import InspectionSnapshot, take_snapshot
from capability_exchange.diagnosis.observations import ObservationKind, OperationalState

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
                    "PostToolUse": [
                        {"matcher": "Write", "hooks": [{"command": "private-runner"}]}
                    ]
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
            {
                "hooks": {
                    "PostToolUse": [
                        {"hooks": [{"command": f"runner --token {canary}"}]}
                    ]
                }
            }
        ),
    )

    rendered = discover_fingerprint(_snapshot(root), collected_at=NOW).model_dump_json()

    assert canary not in rendered
    assert "API_TOKEN" not in rendered
    assert "--token" not in rendered


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
