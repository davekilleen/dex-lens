"""Closed, privacy-safe observations of a personal AI system."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    SafeAttribute,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

NOW = datetime(2026, 8, 27, tzinfo=UTC)
PROVENANCE = {
    "source_id": "scope:primary",
    "source_class": "vault-authored",
    "scope_reference": "scope:sha256:" + "a" * 64,
    "relative_reference": ".claude/skills/daily-plan/SKILL.md",
}


def test_configuration_is_distinct_from_a_verified_outcome() -> None:
    observation = Observation(
        kind=ObservationKind.MCP_SERVER,
        identity="career-data",
        label="Career data",
        operational_state=OperationalState.DECLARED,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference="path-token:abc123",
        ),
        provenance=PROVENANCE,
        attributes=(SafeAttribute(key="transport", value="local-command"),),
    )

    assert observation.operational_state is OperationalState.DECLARED
    assert observation.operational_state is not OperationalState.OUTCOME_VERIFIED


def test_unknown_attribute_keys_and_secret_values_are_refused() -> None:
    with pytest.raises(ValidationError):
        SafeAttribute(key="api_token", value="secret-value")


def test_fingerprint_rejects_duplicate_observation_identity() -> None:
    item = Observation(
        kind=ObservationKind.SKILL,
        identity="daily-plan",
        label="Daily plan",
        operational_state=OperationalState.IMPLEMENTED,
        evidence=EvidenceItem(state="observed", captured_at=NOW, reference="path-token:a"),
        provenance=PROVENANCE,
    )
    with pytest.raises(ValidationError, match="duplicate observation"):
        EvidenceFingerprint(
            adapter_id="claude-code-local",
            collected_at=NOW,
            observations=(item, item),
        )
