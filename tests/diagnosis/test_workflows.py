"""Evidence-bound workflow graph construction."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    EvidenceFingerprint,
    HealthState,
    Observation,
    ObservationKind,
    RuntimeState,
    SafeAttribute,
)
from capability_exchange.diagnosis.workflows import EdgeKind, build_workflow_graph
from capability_exchange.evidence import EvidenceItem, EvidenceState

NOW = datetime(2026, 9, 2, tzinfo=UTC)
PROVENANCE = {
    "source_id": "scope:primary",
    "source_class": "vault-authored",
    "scope_reference": "scope:sha256:" + "a" * 64,
    "relative_reference": "skills/meeting-processor/SKILL.md",
}


def _observation(
    *,
    kind: ObservationKind,
    identity: str,
    configuration: ConfigurationState = ConfigurationState.IMPLEMENTED,
    runtime: RuntimeState = RuntimeState.NOT_ASSESSED,
    health: HealthState = HealthState.NOT_ASSESSED,
    attributes: tuple[SafeAttribute, ...] = (),
    reference: str,
) -> Observation:
    return Observation(
        kind=kind,
        identity=identity,
        label=identity.replace("-", " ").title(),
        configuration_state=configuration,
        runtime_state=runtime,
        health_state=health,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference=reference,
        ),
        provenance=PROVENANCE,
        attributes=attributes,
    )


def meeting_task_person_fingerprint() -> EvidenceFingerprint:
    return EvidenceFingerprint(
        adapter_id="synthetic",
        collected_at=NOW,
        observations=(
            _observation(
                kind=ObservationKind.SKILL,
                identity="meeting-processor",
                attributes=(
                    SafeAttribute(key="trigger-kind", value="meeting"),
                    SafeAttribute(key="action-kind", value="task"),
                    SafeAttribute(key="target-kind", value="person"),
                ),
                reference="file-token:meeting-processor",
            ),
            _observation(
                kind=ObservationKind.INTEGRATION_PROVIDER,
                identity="task-capturer",
                reference="file-token:task-capturer",
            ),
        ),
    )


def configured_only_health_fingerprint() -> EvidenceFingerprint:
    return EvidenceFingerprint(
        adapter_id="synthetic",
        collected_at=NOW,
        observations=(
            _observation(
                kind=ObservationKind.HEALTH_CHECK,
                identity="proactive-health",
                configuration=ConfigurationState.ENABLED,
                runtime=RuntimeState.NOT_ASSESSED,
                health=HealthState.NOT_ASSESSED,
                reference="file-token:proactive-health",
            ),
        ),
    )


def test_meeting_task_person_flow_requires_exact_observations() -> None:
    graph = build_workflow_graph(meeting_task_person_fingerprint())
    assert [(edge.kind, edge.source_id, edge.target_id) for edge in graph.edges] == [
        (EdgeKind.CREATES, "meeting:processor", "task:capturer"),
        (EdgeKind.UPDATES, "meeting:processor", "entity:person"),
    ]
    assert all(len(edge.evidence_ids) >= 2 for edge in graph.edges)


def test_configured_automation_is_not_a_healthy_outcome() -> None:
    graph = build_workflow_graph(configured_only_health_fingerprint())
    outcome = graph.node("outcome:proactive-health")
    assert outcome.runtime_state is RuntimeState.NOT_ASSESSED
    assert outcome.health_state is HealthState.NOT_ASSESSED


def test_structural_attribute_values_must_use_closed_vocabulary() -> None:
    with pytest.raises(ValueError, match="closed vocabulary"):
        SafeAttribute(key="trigger-kind", value="private-meeting-flow")


def test_workflow_graph_is_deterministic() -> None:
    fingerprint = meeting_task_person_fingerprint()
    first = build_workflow_graph(fingerprint)
    second = build_workflow_graph(fingerprint)
    assert first == second
