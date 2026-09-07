"""Evidence-bound workflow graph construction for Lens diagnosis."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    EvidenceFingerprint,
    HealthState,
    Observation,
    ObservationKind,
    RuntimeState,
    observation_id_for,
)
from capability_exchange.diagnosis.run import _ValidatedInventoried, canonical_json_digest

__all__ = [
    "EdgeKind",
    "NodeKind",
    "WorkflowEdge",
    "WorkflowGraph",
    "WorkflowNode",
    "build_workflow_graph",
    "workflow_id_for",
]

_ID = __import__("re").compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")


class NodeKind(StrEnum):
    TRIGGER = "trigger"
    SKILL = "skill"
    MCP_SERVER = "mcp-server"
    MCP_TOOL = "mcp-tool"
    PROVIDER = "provider"
    AUTOMATION = "automation"
    ENTITY = "entity"
    MEMORY = "memory"
    GUARD = "guard"
    OUTCOME = "outcome"


class EdgeKind(StrEnum):
    INVOKES = "invokes"
    READS_FROM = "reads-from"
    CREATES = "creates"
    UPDATES = "updates"
    CHECKS = "checks"
    RECOVERS = "recovers"


def _bounded_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if _ID.fullmatch(value) is None:
            raise ValueError(f"{label} must use bounded identities")
    return values


class WorkflowEdge(_ValidatedInventoried):
    workflow_id: str
    source_id: str
    target_id: str
    kind: EdgeKind
    evidence_ids: tuple[str, ...] = Field(min_length=2, max_length=8)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_ids(values, "workflow edge evidence identities")


class WorkflowNode(_ValidatedInventoried):
    node_id: str
    kind: NodeKind
    configuration_state: ConfigurationState
    runtime_state: RuntimeState
    health_state: HealthState
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=8)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_ids(values, "workflow node evidence identities")


class WorkflowGraph(_ValidatedInventoried):
    nodes: tuple[WorkflowNode, ...]
    edges: tuple[WorkflowEdge, ...]

    def node(self, node_id: str) -> WorkflowNode:
        matches = tuple(item for item in self.nodes if item.node_id == node_id)
        if len(matches) != 1:
            raise KeyError(node_id)
        return matches[0]


def workflow_id_for(
    *,
    source_id: str,
    target_id: str,
    kind: EdgeKind,
) -> str:
    digest = canonical_json_digest(
        {"kind": kind.value, "source_id": source_id, "target_id": target_id}
    )
    return "workflow:" + digest.removeprefix("sha256:")


def _attribute_map(observation: Observation) -> dict[str, str]:
    return {item.key: item.value for item in observation.attributes}


def _node_from_observation(
    *,
    node_id: str,
    kind: NodeKind,
    observation: Observation,
    extra_evidence: tuple[str, ...] = (),
) -> WorkflowNode:
    evidence = (observation_id_for(observation), *extra_evidence)
    return WorkflowNode(
        node_id=node_id,
        kind=kind,
        configuration_state=observation.configuration_state,
        runtime_state=observation.runtime_state,
        health_state=observation.health_state,
        evidence_ids=_bounded_ids(evidence, "workflow node evidence identities"),
    )


def _meeting_task_person_flow(
    observations: tuple[Observation, ...],
) -> tuple[tuple[WorkflowNode, ...], tuple[WorkflowEdge, ...]]:
    skill = next(
        (
            item
            for item in observations
            if item.kind is ObservationKind.SKILL and item.identity == "meeting-processor"
        ),
        None,
    )
    task_adapter = next(
        (
            item
            for item in observations
            if item.kind is ObservationKind.INTEGRATION_PROVIDER
            and item.identity == "task-capturer"
        ),
        None,
    )
    if skill is None or task_adapter is None:
        return (), ()
    attrs = _attribute_map(skill)
    if attrs.get("trigger-kind") != "meeting":
        return (), ()
    if attrs.get("action-kind") != "task":
        return (), ()
    if attrs.get("target-kind") != "person":
        return (), ()
    skill_evidence = observation_id_for(skill)
    task_evidence = observation_id_for(task_adapter)
    meeting_node = _node_from_observation(
        node_id="meeting:processor",
        kind=NodeKind.SKILL,
        observation=skill,
        extra_evidence=(task_evidence,),
    )
    task_node = _node_from_observation(
        node_id="task:capturer",
        kind=NodeKind.ENTITY,
        observation=task_adapter,
        extra_evidence=(skill_evidence,),
    )
    person_node = _node_from_observation(
        node_id="entity:person",
        kind=NodeKind.ENTITY,
        observation=skill,
        extra_evidence=(task_evidence,),
    )
    creates = WorkflowEdge(
        workflow_id=workflow_id_for(
            source_id="meeting:processor",
            target_id="task:capturer",
            kind=EdgeKind.CREATES,
        ),
        source_id="meeting:processor",
        target_id="task:capturer",
        kind=EdgeKind.CREATES,
        evidence_ids=(skill_evidence, task_evidence),
    )
    updates = WorkflowEdge(
        workflow_id=workflow_id_for(
            source_id="meeting:processor",
            target_id="entity:person",
            kind=EdgeKind.UPDATES,
        ),
        source_id="meeting:processor",
        target_id="entity:person",
        kind=EdgeKind.UPDATES,
        evidence_ids=(skill_evidence, task_evidence),
    )
    return (meeting_node, task_node, person_node), (creates, updates)


def _proactive_health_outcome(
    observations: tuple[Observation, ...],
) -> tuple[tuple[WorkflowNode, ...], tuple[WorkflowEdge, ...]]:
    health = next(
        (
            item
            for item in observations
            if item.kind is ObservationKind.HEALTH_CHECK
            and item.identity == "proactive-health"
        ),
        None,
    )
    if health is None:
        return (), ()
    node = _node_from_observation(
        node_id="outcome:proactive-health",
        kind=NodeKind.OUTCOME,
        observation=health,
    )
    return (node,), ()


def build_workflow_graph(fingerprint: EvidenceFingerprint) -> WorkflowGraph:
    """Derive a conservative, evidence-bound workflow graph from one fingerprint."""

    observations = fingerprint.observations
    nodes: list[WorkflowNode] = []
    edges: list[WorkflowEdge] = []
    for builder in (_meeting_task_person_flow, _proactive_health_outcome):
        built_nodes, built_edges = builder(observations)
        nodes.extend(built_nodes)
        edges.extend(built_edges)
    nodes.sort(key=lambda item: (item.kind.value, item.node_id))
    edges.sort(
        key=lambda item: (
            item.kind.value,
            item.source_id,
            item.target_id,
            item.workflow_id,
        )
    )
    return WorkflowGraph(nodes=tuple(nodes), edges=tuple(edges))
