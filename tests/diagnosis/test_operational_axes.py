"""Focused tests for the three-axis observation payload and legacy reads."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.adapters.claude_code.discovery import discover_fingerprint
from capability_exchange.adapters.claude_code.live_state import LiveState
from capability_exchange.adapters.claude_code.snapshot import take_snapshot
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    EvidenceFingerprint,
    HealthState,
    Observation,
    ObservationKind,
    OperationalState,
    RuntimeState,
    migrate_stored_fingerprint_payload,
)
from capability_exchange.diagnosis.run import ApprovedScopeReceipt, canonical_json_digest

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _legacy_payload(state: str = "implemented") -> dict[str, object]:
    return {
        "adapter_id": "synthetic",
        "collected_at": NOW.isoformat(),
        "observations": [
            {
                "kind": "skill",
                "identity": "weekly-plan",
                "label": "Weekly plan",
                "operational_state": state,
                "evidence": {
                    "state": "observed",
                    "captured_at": NOW.isoformat(),
                    "reference": "file-token:weekly-plan.md",
                },
                "provenance": {
                    "source_id": "scope:primary",
                    "source_class": "vault-authored",
                    "scope_reference": "scope:sha256:" + "d" * 64,
                    "relative_reference": "skills/weekly-plan/SKILL.md",
                },
                "attributes": [],
            }
        ],
        "limits": [],
    }


def test_legacy_stored_fingerprint_migrates_once_to_three_axes() -> None:
    migrated = migrate_stored_fingerprint_payload(_legacy_payload())
    observation = migrated["observations"][0]

    assert isinstance(observation, dict)
    assert "operational_state" not in observation
    assert observation["configuration_state"] == ConfigurationState.IMPLEMENTED.value
    assert observation["runtime_state"] == RuntimeState.NOT_ASSESSED.value
    assert observation["health_state"] == HealthState.NOT_ASSESSED.value
    assert "operational_state" not in json.dumps(migrated)
    assert EvidenceFingerprint.model_validate(migrated).observations[0].configuration_state is (
        ConfigurationState.IMPLEMENTED
    )


def test_new_fingerprint_payload_emits_no_competing_operational_scalar() -> None:
    migrated = migrate_stored_fingerprint_payload(_legacy_payload())
    fingerprint = EvidenceFingerprint.model_validate(migrated)
    dumped = fingerprint.model_dump(mode="json")

    assert "operational_state" not in dumped["observations"][0]
    assert {
        "configuration_state",
        "runtime_state",
        "health_state",
    } <= dumped["observations"][0].keys()


def test_migration_is_idempotent_and_refuses_mixed_old_and_new_truths() -> None:
    migrated = migrate_stored_fingerprint_payload(_legacy_payload("loaded"))
    assert migrate_stored_fingerprint_payload(migrated) == migrated

    mixed = _legacy_payload()
    mixed_observation = mixed["observations"][0]
    assert isinstance(mixed_observation, dict)
    mixed_observation["runtime_state"] = RuntimeState.NOT_ASSESSED.value
    with pytest.raises(ValueError, match="operational_state"):
        migrate_stored_fingerprint_payload(mixed)


def test_observation_constructor_refuses_mixed_legacy_scalar_and_axes() -> None:
    mixed = dict(_legacy_payload()["observations"][0])
    mixed["runtime_state"] = RuntimeState.LOADED

    with pytest.raises(ValueError, match="operational_state alongside axis fields"):
        Observation(**mixed)


def test_unknown_axis_values_fail_closed() -> None:
    payload = migrate_stored_fingerprint_payload(_legacy_payload())
    observation = payload["observations"][0]
    assert isinstance(observation, dict)
    observation["health_state"] = "healthy-ish"

    with pytest.raises(ValidationError, match="health_state"):
        EvidenceFingerprint.model_validate(payload)


def test_axis_vocabularies_are_distinct_and_closed() -> None:
    assert ConfigurationState.IMPLEMENTED.value == "implemented"
    assert RuntimeState.LOADED.value == "loaded"
    assert HealthState.HEALTHY.value == "healthy"
    assert ObservationKind.SKILL.value == "skill"
    assert OperationalState.IMPLEMENTED.value == "implemented"


def _automation_snapshot(root: Path):
    path = root / "Library" / "LaunchAgents" / "nightly-check.plist"
    path.parent.mkdir(parents=True)
    path.write_text(
        "<plist><dict><key>Label</key><string>nightly-check</string>"
        "<key>StartCalendarInterval</key><dict/></dict></plist>",
        encoding="utf-8",
    )
    contract = claude_code_contract((str(root.resolve()),))
    allowlist = CanonicalAllowlist(contract.read_scope, denied_paths=contract.denied_paths)
    return take_snapshot(allowlist, taken_at=NOW)


def _receipt(*, include_live_state: bool) -> ApprovedScopeReceipt:
    reference = "scope:sha256:" + "f" * 64
    return ApprovedScopeReceipt(
        run_id="run:" + "a" * 16,
        scope_references=(reference,),
        scope_digest=canonical_json_digest([reference]),
        session_receipt_id="session:synthetic",
        approved_at=NOW,
        include_live_state=include_live_state,
    )


@pytest.mark.parametrize("include_live_state", (False, True))
def test_live_state_updates_runtime_axis_only_when_receipt_allows_it(
    tmp_path: Path, include_live_state: bool
) -> None:
    fingerprint = discover_fingerprint(
        _automation_snapshot(tmp_path),
        collected_at=NOW,
        live_states=(
            LiveState(
                kind="automation",
                identity="nightly-check",
                runtime_state=RuntimeState.LOADED,
                captured_at=NOW,
            ),
        ),
        scope_receipt=_receipt(include_live_state=include_live_state),
    )
    observation = next(
        item
        for item in fingerprint.observations
        if item.kind is ObservationKind.AUTOMATION and item.identity == "nightly-check"
    )

    assert observation.configuration_state is ConfigurationState.IMPLEMENTED
    assert observation.health_state is HealthState.NOT_ASSESSED
    assert observation.runtime_state is (
        RuntimeState.LOADED if include_live_state else RuntimeState.NOT_ASSESSED
    )
