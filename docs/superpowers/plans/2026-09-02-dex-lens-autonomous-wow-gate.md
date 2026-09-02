# Dex Lens Autonomous Wow Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Turn one approved Dex Lens request into an autonomous, evidence-bound whole-system diagnosis with reconstructed workflows, grounded strengths and reciprocal lessons, and up to ten ranked Dex recommendations.

**Architecture:** Extend the existing deterministic diagnosis engine with three focused modules: an engine-owned specialist work queue, a typed workflow graph, and explainable recommendation ranking. The local MCP and CLI remain thin adapters; the chosen host assistant processes bounded work packets, while the engine validates every identity, requires a sceptical pass, owns completion, and renders the canonical result.

**Tech Stack:** Python 3.11+, Pydantic v2, MCP Python SDK, pytest, Hypothesis, Ruff, the existing immutable diagnosis checkpoint store, signed Lens catalogue v2, and the packaged Dex Lens skill.

---

## Delivery boundary

This plan updates the existing Lens draft PR #53 and uses the existing Core
draft PR #689 as signed capability-contract input. It may update Core only if
an additive catalogue-contract field is genuinely required. It does not
authorise merge, release, signing, catalogue publication, installer promotion,
website deployment, or a production change.

The private evaluation repository is read-only evaluation input. Its name,
paths, raw report, observations, proposal text, and content must never enter a
commit, CI log, PR, Mission Control, or Dispatch.

## File structure

New Lens modules:

- src/capability_exchange/diagnosis/work.py — work packets, queue state,
  receipts, provenance, and bounded retries.
- src/capability_exchange/diagnosis/workflows.py — typed workflow nodes,
  evidence-bound edges, and graph construction.
- src/capability_exchange/diagnosis/ranking.py — recommendation factors,
  eligibility, deterministic ordering, and ranks 1–10.
- src/capability_exchange/diagnosis/expectations.py — the versioned fourteen-
  family expectation manifest.
- src/capability_exchange/diagnosis/automatic.py — conservative findings
  produced without a language model.
- src/capability_exchange/diagnosis/wow_gate.py and scripts/run_wow_gate.py —
  the aggregate scorecard and hard-failure evaluator.

Existing Lens modules changed:

- specialists.py — packet-bound validation and the ten-item ceiling.
- run.py, orchestrator.py, and run_store.py — guided analysis state and audit.
- defaults.py — graph, automatic candidate, and comparer wiring.
- comparison.py and report.py — canonical workflows, rank, praise, and lessons.
- mcp_server.py and cli.py — one shared get-work/submit protocol.
- observations.py and adapters/claude_code/discovery.py — reviewed structural
  relationship tokens only.
- boundary/data_inventory.yaml — every new stored or transmitted field.
- skill/dex-lens/SKILL.md — the one-request loop for every supported host.

## Task 1: Raise the recommendation ceiling and make ranking explicit

**Files:**

- Create: src/capability_exchange/diagnosis/ranking.py
- Create: tests/diagnosis/test_ranking.py
- Modify: src/capability_exchange/diagnosis/specialists.py
- Modify: src/capability_exchange/diagnosis/comparison.py
- Modify: tests/diagnosis/test_specialists.py
- Modify: tests/diagnosis/test_comparison.py
- Modify: src/capability_exchange/boundary/data_inventory.yaml

- [ ] **Step 1: Write the failing ceiling and ordering tests**

~~~python
def test_ten_recommendations_are_allowed_but_eleven_are_refused() -> None:
    context = proposal_context(catalogue_ids=tuple(f"cap-{n}" for n in range(11)))
    ten = tuple(recommendation(f"cap-{n}") for n in range(10))
    assert len(reconcile_proposals(ten, context=context)) == 10
    with pytest.raises(SpecialistProposalError, match="at most 10"):
        reconcile_proposals((*ten, recommendation("cap-10")), context=context)


def test_recommendations_have_one_stable_explainable_order() -> None:
    candidates = (
        candidate("high-effort", relevance=3, leverage=3, evidence=3, effort=3),
        candidate("low-effort", relevance=3, leverage=3, evidence=3, effort=1),
        candidate("urgent", risk=3, relevance=1, leverage=1, evidence=2, effort=3),
    )
    ranked = rank_recommendations(candidates)
    assert [(item.rank, item.catalogue_id) for item in ranked] == [
        (1, "urgent"),
        (2, "low-effort"),
        (3, "high-effort"),
    ]
~~~

- [ ] **Step 2: Run the focused tests and observe the old cap fail**

Run:

~~~bash
python3 -m pytest tests/diagnosis/test_ranking.py \
  tests/diagnosis/test_specialists.py::test_recommendation_cap_is_enforced_at_set_level \
  tests/diagnosis/test_comparison.py -q
~~~

Expected: failure because ranking.py does not exist and the current cap is
three.

- [ ] **Step 3: Add the closed ranking domain**

Implement these public types and ordering rule in ranking.py:

~~~python
MAX_RECOMMENDATIONS = 10


class RecommendationFactors(_ValidatedInventoried):
    reliability_risk: int = Field(ge=0, le=3)
    job_relevance: int = Field(ge=0, le=3)
    workflow_leverage: int = Field(ge=0, le=3)
    evidence_strength: int = Field(ge=1, le=3)
    adoption_effort: int = Field(ge=1, le=3)


class RecommendationCandidate(_ValidatedInventoried):
    catalogue_id: str = Field(pattern=_ID.pattern)
    capability_id: str = Field(pattern=_ID.pattern)
    factors: RecommendationFactors
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    observation_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=600)


class RankedRecommendation(RecommendationCandidate):
    rank: int = Field(ge=1, le=MAX_RECOMMENDATIONS)


def rank_recommendations(
    candidates: Iterable[RecommendationCandidate],
) -> tuple[RankedRecommendation, ...]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            -item.factors.reliability_risk,
            -item.factors.job_relevance,
            -item.factors.workflow_leverage,
            -item.factors.evidence_strength,
            item.factors.adoption_effort,
            item.catalogue_id,
        ),
    )
    if len(ordered) > MAX_RECOMMENDATIONS:
        raise ValueError("a diagnosis may recommend at most 10 Dex additions")
    return tuple(
        RankedRecommendation(**item.model_dump(), rank=index)
        for index, item in enumerate(ordered, start=1)
    )
~~~

Import the one MAX_RECOMMENDATIONS constant in specialists and comparison;
delete the duplicated constant and every hard-coded “three” error. Add factors
to validated recommendation proposals and the exact ranked tuple to
ComparisonLedger.

- [ ] **Step 4: Inventory the fields and prove the slice**

~~~bash
python3 scripts/check_inventory.py
python3 -m pytest tests/diagnosis/test_ranking.py \
  tests/diagnosis/test_specialists.py tests/diagnosis/test_comparison.py -q
~~~

Expected: all pass.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/ranking.py \
  src/capability_exchange/diagnosis/specialists.py \
  src/capability_exchange/diagnosis/comparison.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_ranking.py tests/diagnosis/test_specialists.py \
  tests/diagnosis/test_comparison.py
git commit -m "feat: rank up to ten Lens recommendations"
~~~

## Task 2: Add the engine-owned specialist work queue

**Files:**

- Create: src/capability_exchange/diagnosis/work.py
- Create: tests/diagnosis/test_work.py
- Modify: src/capability_exchange/diagnosis/specialists.py
- Modify: src/capability_exchange/boundary/data_inventory.yaml

- [ ] **Step 1: Write failing packet and receipt tests**

~~~python
def test_guided_queue_issues_normal_roles_before_sceptical_review() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    assert tuple(packet.role for packet in queue.pending_packets()) == NORMAL_ROLES
    assert SpecialistRole.SCEPTICAL_RECONCILER not in {
        packet.role for packet in queue.pending_packets()
    }


def test_same_response_is_idempotent_but_changed_response_is_refused() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.pending_packets()[0]
    receipt = response_receipt(packet, response_digest="sha256:" + "a" * 64)
    once = queue.record(receipt)
    assert once.record(receipt) == once
    with pytest.raises(WorkQueueError, match="different response"):
        once.record(response_receipt(packet, response_digest="sha256:" + "b" * 64))
~~~

- [ ] **Step 2: Run the test and observe the missing module**

Run: python3 -m pytest tests/diagnosis/test_work.py -q

Expected: collection fails because diagnosis.work is absent.

- [ ] **Step 3: Implement immutable work types**

~~~python
class AnalysisMode(StrEnum):
    INVENTORY_ONLY = "inventory-only"
    GUIDED = "guided-analysis"


class WorkStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    INSUFFICIENT = "insufficient"
    UNRESOLVED = "unresolved"


class WorkQueueError(ValueError):
    pass


NORMAL_ROLES = (
    SpecialistRole.TOOLS_AND_INTEGRATIONS,
    SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
    SpecialistRole.PEOPLE_AND_WORK_CONTINUITY,
    SpecialistRole.OPERATING_RHYTHM_AND_MEMORY,
    SpecialistRole.STRENGTH_AND_RECIPROCAL,
    SpecialistRole.RELEASE_DISTANCE,
    SpecialistRole.CONTRADICTIONS_AND_RELIABILITY,
    SpecialistRole.WORKFLOW_SYNTHESIS,
)


class WorkPacket(_ValidatedInventoried):
    packet_id: str
    packet_digest: str
    role: SpecialistRole
    run_id: str
    fingerprint_digest: str
    catalogue_digest: str
    evidence_ids: tuple[str, ...]
    catalogue_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    family_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    question: str
    max_proposals: int = Field(ge=0, le=24)


class WorkReceipt(_ValidatedInventoried):
    packet_id: str
    packet_digest: str
    response_digest: str
    status: WorkStatus
    submission_route: Literal["engine-work-packet"] = "engine-work-packet"
    proposal_count: int = Field(ge=0, le=24)


class WorkQueue(_ValidatedInventoried):
    mode: AnalysisMode
    packets: tuple[WorkPacket, ...]
    receipts: tuple[WorkReceipt, ...] = ()
    sceptical_packet_id: str | None = None

    def pending_packets(self) -> tuple[WorkPacket, ...]:
        completed = {item.packet_id for item in self.receipts}
        normal = tuple(
            item for item in self.packets
            if item.packet_id not in completed
            and item.role is not SpecialistRole.SCEPTICAL_RECONCILER
        )
        if normal:
            return normal
        return tuple(item for item in self.packets if item.packet_id not in completed)

    def complete(self) -> bool:
        return not self.pending_packets()

    def require_pending(self, packet_id: str) -> WorkPacket:
        matches = tuple(item for item in self.packets if item.packet_id == packet_id)
        if len(matches) != 1:
            raise WorkQueueError("packet is not in this work queue")
        if packet_id in {item.packet_id for item in self.receipts}:
            raise WorkQueueError("packet already has a response")
        return matches[0]

    def record(self, receipt: WorkReceipt) -> WorkQueue:
        existing = tuple(item for item in self.receipts if item.packet_id == receipt.packet_id)
        if existing:
            if existing == (receipt,):
                return self
            raise WorkQueueError("packet already has a different response")
        packet = self.require_pending(receipt.packet_id)
        if receipt.packet_digest != packet.packet_digest:
            raise WorkQueueError("response packet digest does not match issued work")
        return self.model_copy(update={"receipts": (*self.receipts, receipt)})


class WorkAudit(_ValidatedInventoried):
    mode: AnalysisMode
    packet_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    manual_submission_count: int = Field(ge=0)
    receipts: tuple[WorkReceipt, ...]
~~~

Generate packet IDs and digests from canonical JSON over the exact role and
allowed identities. Inventory-only creates no packets. Guided analysis creates
the eight normal roles followed by one locked sceptical packet. Add the three
new role names in NORMAL_ROLES to SpecialistRole; the existing role values
remain unchanged.

- [ ] **Step 4: Run inventory and work tests**

~~~bash
python3 scripts/check_inventory.py
python3 -m pytest tests/diagnosis/test_work.py -q
~~~

Expected: both pass.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/work.py \
  src/capability_exchange/diagnosis/specialists.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_work.py
git commit -m "feat: add engine-owned Lens work packets"
~~~

## Task 3: Bind every semantic proposal to issued work

**Files:**

- Modify: src/capability_exchange/diagnosis/specialists.py
- Modify: tests/diagnosis/test_specialists.py
- Modify: src/capability_exchange/boundary/data_inventory.yaml

- [ ] **Step 1: Write failing packet-binding tests**

~~~python
def test_guided_proposal_must_match_packet_identity_and_digest() -> None:
    packet = issued_packet()
    context = proposal_context(packet=packet)
    proposal = recommendation(
        "cap-one",
        packet_id=packet.packet_id,
        packet_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(SpecialistProposalError, match="packet digest"):
        validate_proposal(proposal, context)


def test_sceptical_role_cannot_add_a_new_positive_claim() -> None:
    packet = issued_sceptical_packet(candidate_ids=("candidate-one",))
    proposal = recommendation("cap-new", packet=packet)
    with pytest.raises(SpecialistProposalError, match="accept or downgrade"):
        validate_proposal(proposal, proposal_context(packet=packet))
~~~

- [ ] **Step 2: Observe the failures**

Run: python3 -m pytest tests/diagnosis/test_specialists.py -q

Expected: the new tests fail because validation knows only run, fingerprint,
and catalogue context.

- [ ] **Step 3: Extend the closed proposal contract**

Add these fields to SpecialistProposal and ValidatedProposal:

~~~python
packet_id: str | None = Field(default=None, pattern=_PACKET_ID.pattern)
packet_digest: str | None = Field(default=None, pattern=_SHA256.pattern)
recommendation_factors: RecommendationFactors | None = None
candidate_id: str | None = Field(default=None, pattern=_ID.pattern)
~~~

Add scalar packet context rather than importing work.py back into
specialists.py:

~~~python
packet_id: str | None = Field(default=None, pattern=_PACKET_ID.pattern)
packet_digest: str | None = Field(default=None, pattern=_SHA256.pattern)
packet_role: SpecialistRole | None = None
accepted_candidate_ids: tuple[str, ...] = ()
~~~

Require both packet
fields when packet_id is present, compare every allowed identity set, require
factors for recommendations, and allow the sceptical role only to accept,
downgrade, or reject an existing candidate. Retain unbound proposals only for
inventory-only stored-run compatibility.

- [ ] **Step 4: Run specialists and inventory checks**

~~~bash
python3 scripts/check_inventory.py
python3 -m pytest tests/diagnosis/test_specialists.py -q
~~~

Expected: all pass, including model-copy/construct bypass tests.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/specialists.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_specialists.py
git commit -m "feat: bind Lens proposals to issued work"
~~~

## Task 4: Put guided analysis into the durable engine state machine

**Files:**

- Modify: src/capability_exchange/diagnosis/run.py
- Modify: src/capability_exchange/diagnosis/orchestrator.py
- Modify: src/capability_exchange/diagnosis/run_store.py
- Modify: tests/diagnosis/test_run.py
- Modify: tests/diagnosis/test_run_store.py
- Modify: tests/diagnosis/test_orchestrator.py
- Modify: tests/evals/test_interrupted_run.py
- Modify: src/capability_exchange/boundary/data_inventory.yaml

- [ ] **Step 1: Write failing guided-state tests**

~~~python
def test_guided_run_refuses_comparison_until_work_is_reconciled(
    engine: EngineHarness,
) -> None:
    run_id = engine.advance_to_jobs_confirmed(mode=AnalysisMode.GUIDED)
    assert engine.real.advance(run_id).stage is DiagnosisStage.ANALYSIS_PLANNED
    with pytest.raises(DiagnosisStateError, match="specialist work remains"):
        engine.real.advance(run_id)


def test_resumed_run_returns_the_same_next_packet(engine: EngineHarness) -> None:
    run_id = engine.advance_to_analysis_planned(mode=AnalysisMode.GUIDED)
    first = engine.real.work(run_id)
    assert engine.reopen().work(run_id) == first
~~~

- [ ] **Step 2: Observe state-machine failures**

~~~bash
python3 -m pytest tests/diagnosis/test_run.py \
  tests/diagnosis/test_run_store.py tests/diagnosis/test_orchestrator.py \
  tests/evals/test_interrupted_run.py -q
~~~

Expected: failures for absent stages, mode, and work method.

- [ ] **Step 3: Add stages, mode, and engine methods**

Add ANALYSIS_PLANNED and ANALYSIS_COMPLETED between JOBS_CONFIRMED and
COMPARED. Add analysis_mode to DiagnosisInput and PrepareDiagnosisRequest,
default new product runs to GUIDED, and upgrade old inputs to INVENTORY_ONLY.

~~~python
def work(self, run_id: str) -> WorkPacket | None:
    checkpoint = self._load(run_id)
    if checkpoint.stage is not DiagnosisStage.ANALYSIS_PLANNED:
        raise DiagnosisStateError(
            "specialist work is available only after analysis planning"
        )
    pending = self._work_queue(checkpoint).pending_packets()
    return pending[0] if pending else None


def submit_work(
    self,
    run_id: str,
    packet_id: str,
    proposals: tuple[SpecialistProposal, ...],
) -> DiagnosisRunView:
    checkpoint = self._load(run_id)
    queue = self._work_queue(checkpoint)
    packet = queue.require_pending(packet_id)
    validated = tuple(
        validate_proposal(
            item,
            self._proposal_context_for_packet(checkpoint, packet),
        )
        for item in proposals
    )
    return self._record_work_response(
        checkpoint,
        queue,
        packet,
        validated,
    )
~~~

JOBS_CONFIRMED to ANALYSIS_PLANNED stores graph, automatic candidates, and
queue. ANALYSIS_PLANNED to ANALYSIS_COMPLETED refuses until every normal and
sceptical receipt exists. ANALYSIS_COMPLETED to COMPARED builds the ledger.

- [ ] **Step 4: Prove checkpoint and resume behaviour**

~~~bash
python3 scripts/check_inventory.py
python3 -m pytest tests/diagnosis/test_run.py \
  tests/diagnosis/test_run_store.py tests/diagnosis/test_orchestrator.py \
  tests/evals/test_interrupted_run.py -q
~~~

Expected: all pass; resuming never duplicates a packet or response.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/run.py \
  src/capability_exchange/diagnosis/orchestrator.py \
  src/capability_exchange/diagnosis/run_store.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_run.py tests/diagnosis/test_run_store.py \
  tests/diagnosis/test_orchestrator.py tests/evals/test_interrupted_run.py
git commit -m "feat: make guided Lens analysis engine-owned"
~~~

## Task 5: Expose the same work protocol through MCP and CLI

**Files:**

- Modify: src/capability_exchange/diagnosis/mcp_server.py
- Modify: src/capability_exchange/diagnosis/cli.py
- Modify: tests/diagnosis/test_mcp_server.py
- Modify: tests/diagnosis/test_cli.py
- Modify: tests/evals/test_adapter_conformance.py
- Modify: tests/diagnosis/test_conformance_351_352.py

- [ ] **Step 1: Write failing six-tool and equality tests**

~~~python
def test_mcp_exposes_exactly_six_read_only_diagnosis_tools() -> None:
    server = build_mcp_server(FixedEngine())
    assert {tool.name for tool in server._tool_manager.list_tools()} == {
        "prepare_diagnosis",
        "get_diagnosis_status",
        "advance_diagnosis",
        "get_diagnosis_work",
        "submit_specialist_proposal",
        "get_diagnosis_result",
    }


def test_direct_cli_and_mcp_return_identical_work_bytes(
    conformance: AdapterHarness,
) -> None:
    assert conformance.direct_work_bytes() == conformance.cli_work_bytes()
    assert conformance.cli_work_bytes() == conformance.mcp_work_bytes()
~~~

- [ ] **Step 2: Observe missing surfaces**

Run: python3 -m pytest tests/diagnosis/test_mcp_server.py
tests/diagnosis/test_cli.py tests/evals/test_adapter_conformance.py
tests/diagnosis/test_conformance_351_352.py -q

Expected: failures because MCP has five tools and CLI has no work command.

- [ ] **Step 3: Add thin adapter support**

Register:

~~~python
@server.tool(annotations=_READ_ONLY)
def get_diagnosis_work(run_id: str) -> dict[str, object]:
    """Return the next engine-issued packet, or a typed empty result."""
    packet = engine.work(run_id)
    return {"packet": None if packet is None else packet.dump_for_storage()}
~~~

Change submission to accept run_id, packet_id, and proposals and call
engine.submit_work. Add CLI forms:

~~~text
dex-lens diagnosis prepare --root <folder> --mode guided-analysis
dex-lens diagnosis work --run <id> --json
dex-lens diagnosis submit --run <id> --packet <id> --proposal <json-file>
~~~

Both adapters use canonical compact JSON and keep stdout protocol-only.

- [ ] **Step 4: Run conformance and hostile-field tests**

~~~bash
python3 -m pytest tests/diagnosis/test_mcp_server.py \
  tests/diagnosis/test_cli.py tests/evals/test_adapter_conformance.py \
  tests/diagnosis/test_conformance_351_352.py -q
~~~

Expected: all pass.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/mcp_server.py \
  src/capability_exchange/diagnosis/cli.py \
  tests/diagnosis/test_mcp_server.py tests/diagnosis/test_cli.py \
  tests/evals/test_adapter_conformance.py \
  tests/diagnosis/test_conformance_351_352.py
git commit -m "feat: expose Lens specialist work through MCP"
~~~

## Task 6: Reconstruct safe connected workflows

**Files:**

- Create: src/capability_exchange/diagnosis/workflows.py
- Create: tests/diagnosis/test_workflows.py
- Modify: src/capability_exchange/diagnosis/observations.py
- Modify: src/capability_exchange/adapters/claude_code/discovery.py
- Modify: tests/adapters/claude_code/test_discovery.py
- Modify: src/capability_exchange/boundary/data_inventory.yaml

- [ ] **Step 1: Write failing graph tests**

~~~python
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
~~~

- [ ] **Step 2: Observe the missing graph module**

Run: python3 -m pytest tests/diagnosis/test_workflows.py -q

Expected: import failure.

- [ ] **Step 3: Add closed graph models and reviewed attributes**

~~~python
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


class WorkflowEdge(_ValidatedInventoried):
    workflow_id: str
    source_id: str
    target_id: str
    kind: EdgeKind
    evidence_ids: tuple[str, ...] = Field(min_length=2, max_length=8)


class WorkflowNode(_ValidatedInventoried):
    node_id: str
    kind: NodeKind
    configuration_state: ConfigurationState
    runtime_state: RuntimeState
    health_state: HealthState
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=8)


class WorkflowGraph(_ValidatedInventoried):
    nodes: tuple[WorkflowNode, ...]
    edges: tuple[WorkflowEdge, ...]

    def node(self, node_id: str) -> WorkflowNode:
        matches = tuple(item for item in self.nodes if item.node_id == node_id)
        if len(matches) != 1:
            raise KeyError(node_id)
        return matches[0]
~~~

Allow structural keys trigger-kind, action-kind, output-kind, target-kind, and
guard-kind. Values come only from a closed vocabulary such as meeting, task,
person, company, memory, backup, health, and external-task. Raw commands,
arguments, paths, account names, and prose remain unrepresentable.

- [ ] **Step 4: Prove graph determinism and privacy**

~~~bash
python3 scripts/check_inventory.py
python3 -m pytest tests/diagnosis/test_workflows.py \
  tests/adapters/claude_code/test_discovery.py \
  tests/diagnosis/test_observations.py -q
~~~

Expected: stable ordering, no single-evidence cross-surface edge, no raw
path/content field, and honest operational axes.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/workflows.py \
  src/capability_exchange/diagnosis/observations.py \
  src/capability_exchange/adapters/claude_code/discovery.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_workflows.py \
  tests/adapters/claude_code/test_discovery.py \
  tests/diagnosis/test_observations.py
git commit -m "feat: reconstruct evidence-bound Lens workflows"
~~~

## Task 7: Guarantee all significant families and generate conservative facts

**Files:**

- Create: src/capability_exchange/diagnosis/expectations.py
- Create: src/capability_exchange/diagnosis/automatic.py
- Create: tests/diagnosis/test_expectations.py
- Create: tests/diagnosis/test_automatic.py
- Modify: src/capability_exchange/diagnosis/defaults.py
- Modify: src/capability_exchange/diagnosis/significant_families.py
- Modify: tests/diagnosis/test_significant_family_assessment.py
- Modify: tests/diagnosis/test_significant_engine_slice.py

- [ ] **Step 1: Write failing manifest and automatic-fact tests**

~~~python
def test_wow_manifest_names_every_agreed_family_once() -> None:
    assert tuple(item.family_id for item in WOW_EXPECTATIONS) == (
        "meeting-follow-through",
        "living-people-company-context",
        "durable-task-continuity",
        "external-task-interoperability",
        "connected-work-context",
        "pipedrive-pipeline-continuity",
        "daily-weekly-operating-rhythm",
        "durable-work-memory",
        "proactive-health-and-recovery",
        "backup-and-restore-confidence",
        "safe-change-and-rewind",
        "capability-discovery-and-adoption",
        "privacy-safe-feedback-loop",
        "career-growth-evidence",
    )


def test_restore_is_suggested_only_when_backup_work_is_relevant() -> None:
    candidates = build_automatic_candidates(
        catalogue=available_backup_catalogue(),
        fingerprint=configured_backup_without_restore_proof(),
        workflows=backup_workflow(),
        family_assessments=family_assessments(),
    )
    assert [item.catalogue_id for item in candidates] == ["backup-restore"]
~~~

- [ ] **Step 2: Observe missing modules**

~~~bash
python3 -m pytest tests/diagnosis/test_expectations.py \
  tests/diagnosis/test_automatic.py \
  tests/diagnosis/test_significant_family_assessment.py \
  tests/diagnosis/test_significant_engine_slice.py -q
~~~

Expected: import failures for expectations and automatic.

- [ ] **Step 3: Implement closed expectations and conservative rules**

~~~python
class ExpectationState(StrEnum):
    PRESENT = "present"
    PARTIAL = "partial"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    NOT_RELEVANT = "not-relevant"
    NOT_CURRENTLY_AVAILABLE = "not-currently-available"


class SignificantExpectation(_ValidatedInventoried):
    family_id: str
    state: ExpectationState
    evidence_ids: tuple[str, ...]
    reason: str
~~~

assess_wow_expectations joins the fixed IDs to exact signed family rows;
missing or duplicate rows fail closed. build_automatic_candidates may emit
only reviewed rules with complete typed preconditions. Start with skill-variant
grading, configured backup without restore proof, automation with broken/stale
live evidence, and an available family gap connected to an observed workflow.
Everything else stays with bounded specialists.

A guided-analysis run requires the complete signed family contract. A legacy
family-free catalogue may still close through inventory-only mode, carries no
Wow grade, and cannot be described as a full diagnosis.

- [ ] **Step 4: Prove the expectation and automatic rules**

~~~bash
python3 -m pytest tests/diagnosis/test_expectations.py \
  tests/diagnosis/test_automatic.py \
  tests/diagnosis/test_significant_family_assessment.py \
  tests/diagnosis/test_significant_engine_slice.py \
  tests/diagnosis/test_defaults.py -q
~~~

Expected: all pass and no configuration-only health claim.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/expectations.py \
  src/capability_exchange/diagnosis/automatic.py \
  src/capability_exchange/diagnosis/defaults.py \
  src/capability_exchange/diagnosis/significant_families.py \
  tests/diagnosis/test_expectations.py tests/diagnosis/test_automatic.py \
  tests/diagnosis/test_significant_family_assessment.py \
  tests/diagnosis/test_significant_engine_slice.py
git commit -m "feat: guarantee significant Lens outcome coverage"
~~~

## Task 8: Bind rich analysis into the canonical report

**Files:**

- Modify: src/capability_exchange/diagnosis/comparison.py
- Modify: src/capability_exchange/diagnosis/report.py
- Modify: src/capability_exchange/diagnosis/orchestrator.py
- Modify: tests/diagnosis/test_family_ledger_report.py
- Modify: tests/diagnosis/test_report_model.py
- Modify: tests/diagnosis/test_orchestrator.py
- Modify: tests/reports/test_report_store.py
- Modify: tests/reports/test_ledger.py
- Modify: src/capability_exchange/boundary/data_inventory.yaml

- [ ] **Step 1: Write failing canonical-report tests**

~~~python
def test_report_renders_ranking_strengths_lessons_and_connections() -> None:
    report = result_with_rich_grounded_findings().render_markdown()
    assert "## The best first move" in report
    assert "## Next most useful" in report
    assert "## Also worth considering" in report
    assert "## What is especially strong here" in report
    assert "## What Dex should learn from you" in report
    assert "## Connections Lens noticed" in report


def test_report_rejects_an_insight_without_bound_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        ReportModel.from_result(**unsupported_cross_surface_result())
~~~

- [ ] **Step 2: Observe missing structured content**

~~~bash
python3 -m pytest tests/diagnosis/test_family_ledger_report.py \
  tests/diagnosis/test_report_model.py tests/diagnosis/test_orchestrator.py \
  tests/reports/test_report_store.py tests/reports/test_ledger.py -q
~~~

Expected: failures because work, workflows, expectations, rank, and reciprocal
findings are not canonical ledger inputs.

- [ ] **Step 3: Extend ledger and report construction**

Add exact fields:

~~~python
class InsightKind(StrEnum):
    STRENGTH = "strength"
    RECIPROCAL_LESSON = "reciprocal-lesson"
    WORKFLOW_CONNECTION = "workflow-connection"
    RELIABILITY_CONCERN = "reliability-concern"


class GroundedInsight(_ValidatedInventoried):
    insight_id: str
    kind: InsightKind
    title: str
    explanation: str
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    observation_ids: tuple[str, ...] = ()
    workflow_ids: tuple[str, ...] = ()


workflow_graph: WorkflowGraph
work_audit: WorkAudit
expectations: tuple[SignificantExpectation, ...]
ranked_recommendations: tuple[RankedRecommendation, ...]
strengths: tuple[GroundedInsight, ...]
reciprocal_lessons: tuple[GroundedInsight, ...]
workflow_insights: tuple[GroundedInsight, ...]
~~~

Derive them from the pinned fingerprint, catalogue, receipts, and reconciled
proposals. Extend canonical payload, digest, appendix, stored result, checker,
and reloader together. Render plain-English availability only; do not display
internal “parked” or “dormant” labels.

- [ ] **Step 4: Prove render, reload, and tamper refusal**

~~~bash
python3 scripts/check_inventory.py
python3 -m pytest tests/diagnosis/test_family_ledger_report.py \
  tests/diagnosis/test_report_model.py tests/diagnosis/test_orchestrator.py \
  tests/reports/test_report_store.py tests/reports/test_ledger.py -q
~~~

Expected: all pass; changing any rank, edge, receipt, expectation, or evidence
identity fails reload/check.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/comparison.py \
  src/capability_exchange/diagnosis/report.py \
  src/capability_exchange/diagnosis/orchestrator.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_family_ledger_report.py \
  tests/diagnosis/test_report_model.py tests/diagnosis/test_orchestrator.py \
  tests/reports/test_report_store.py tests/reports/test_ledger.py
git commit -m "feat: render the autonomous Lens diagnosis"
~~~

## Task 9: Make the packaged skill complete the loop in any host

**Files:**

- Modify: src/capability_exchange/skill/dex-lens/SKILL.md
- Modify: tests/test_skill_deterministic_engine.py
- Modify: tests/test_skill_complete_diagnosis.py
- Modify: tests/test_skill_report_template.py
- Modify: tests/test_packaging.py

- [ ] **Step 1: Write failing one-request tests**

~~~python
def test_skill_drives_guided_work_without_stage_prompts() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "get_diagnosis_work" in text
    assert "process every engine-issued packet" in text
    assert "never ask the person to prompt the next diagnosis stage" in text
    assert "submit the specialist response unchanged" in text
    assert "up to ten" in text


def test_skill_has_parallel_and_sequential_host_routes() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "run independent packets in parallel" in text
    assert "process the same packets sequentially" in text
~~~

- [ ] **Step 2: Observe missing guidance**

~~~bash
python3 -m pytest tests/test_skill_deterministic_engine.py \
  tests/test_skill_complete_diagnosis.py tests/test_skill_report_template.py \
  tests/test_packaging.py -q
~~~

Expected: new assertions fail.

- [ ] **Step 3: Replace manual checklist prose with the engine loop**

Add this exact host-neutral behaviour:

~~~text
After scope approval, keep following the engine until it closes:
1. Read status; never maintain a separate checklist or total.
2. If the engine asks for work, fetch the next packet.
3. If this host supports sub-agents, run independent packets in parallel.
   Otherwise process the same packets sequentially in this conversation.
4. Give each worker only the packet. Submit the specialist response unchanged.
5. When no packet remains, advance the engine and repeat.
6. Stop only for a real person decision, an explicit engine error, or closed.
Never ask the person to prompt the next diagnosis stage.
~~~

Explain MCP once as the local structured connection between assistant and Lens.
Preserve fresh-first-look, consent, read-only, no repair/share crossover,
catalogue verification, and engine-owned close.

- [ ] **Step 4: Prove skill and wheel content**

~~~bash
python3 -m pytest tests/test_skill_deterministic_engine.py \
  tests/test_skill_complete_diagnosis.py tests/test_skill_report_template.py \
  tests/test_packaging.py -q
~~~

Expected: all pass.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/skill/dex-lens/SKILL.md \
  tests/test_skill_deterministic_engine.py \
  tests/test_skill_complete_diagnosis.py \
  tests/test_skill_report_template.py tests/test_packaging.py
git commit -m "feat: make Lens diagnosis one continuous request"
~~~

## Task 10: Add the automated Wow Gate

**Files:**

- Create: src/capability_exchange/diagnosis/wow_gate.py
- Create: scripts/run_wow_gate.py
- Create: tests/evals/test_wow_gate.py
- Modify: src/capability_exchange/boundary/data_inventory.yaml
- Modify: pyproject.toml

- [ ] **Step 1: Write failing score and provenance tests**

~~~python
def test_high_score_with_manual_proposal_is_a_hard_failure() -> None:
    grade = grade_wow_run(high_quality_result(), audit_with_manual_submission())
    assert grade.score >= 90
    assert grade.passed is False
    assert "manual-proposal" in grade.hard_failures


def test_rich_run_needs_all_expectations_and_a_surprise() -> None:
    grade = grade_wow_run(rich_result(), autonomous_audit())
    assert grade.score >= 90
    assert grade.hard_failures == ()
    assert grade.passed is True
~~~

- [ ] **Step 2: Observe the missing grader**

Run: python3 -m pytest tests/evals/test_wow_gate.py -q

Expected: import failure.

- [ ] **Step 3: Implement typed scoring and hard failures**

~~~python
class WowGrade(_ValidatedInventoried):
    significant_coverage: int = Field(ge=0, le=25)
    workflow_quality: int = Field(ge=0, le=20)
    recommendation_quality: int = Field(ge=0, le=20)
    reciprocal_quality: int = Field(ge=0, le=15)
    evidence_integrity: int = Field(ge=0, le=15)
    autonomy_and_clarity: int = Field(ge=0, le=5)
    hard_failures: tuple[str, ...]

    @property
    def score(self) -> int:
        return (
            self.significant_coverage
            + self.workflow_quality
            + self.recommendation_quality
            + self.reciprocal_quality
            + self.evidence_integrity
            + self.autonomy_and_clarity
        )

    @property
    def passed(self) -> bool:
        return self.score >= 90 and not self.hard_failures
~~~

Derive points from typed result fields, never prose. Hard failures include
manual/unbound proposal provenance, incomplete packets, missing expectation
IDs, more than ten recommendations, unsupported claims, dishonest operational
state, missing rich-system surprise, digest drift, and private canaries. The
script reads closed result/audit paths, emits aggregate JSON, and never prints
proposal text.

- [ ] **Step 4: Prove score, CLI, privacy, and inventory**

~~~bash
python3 scripts/check_inventory.py
python3 -m pytest tests/evals/test_wow_gate.py \
  tests/boundary/test_inventory.py -q
~~~

Expected: all pass.

- [ ] **Step 5: Commit**

~~~bash
git add src/capability_exchange/diagnosis/wow_gate.py \
  scripts/run_wow_gate.py tests/evals/test_wow_gate.py \
  src/capability_exchange/boundary/data_inventory.yaml pyproject.toml
git commit -m "test: add the autonomous Lens Wow Gate"
~~~

## Task 11: Run the private no-help iteration loop

**Files:**

- Private temporary directory outside every repository
- Add only invented/sanitised fixtures under tests/fixtures/evals
- Modify only the narrow production/tests implicated by each proved miss

- [ ] **Step 1: Create a disposable read-only checkout**

The executing session receives the private source URL directly from Dave and
keeps it in a variable that is never printed:

~~~bash
test -n "$DEX_LENS_PRIVATE_EVAL_SOURCE"
eval_dir="$(mktemp -d /srv/dex-dev/private-evals/lens-wow.XXXXXX)"
gh repo clone "$DEX_LENS_PRIVATE_EVAL_SOURCE" "$eval_dir/source" -- --filter=blob:none
git -C "$eval_dir/source" rev-parse HEAD > "$eval_dir/source-commit"
chmod -R a-w "$eval_dir/source"
~~~

Do not use set -x. Do not print the URL, checkout path, tree, filenames, raw
observations, report, or proposals.

- [ ] **Step 2: Run one product request without evaluator conclusions**

Use the current package, local consent, and guided engine/MCP loop.
The orchestrating agent may dispatch engine-issued packets to specialist
agents, but passes packets and their returned payloads unchanged. It creates or
edits no proposal content. Store result.json, audit.json, report.md, and stderr
only in the private temporary directory.

~~~bash
python3 scripts/run_wow_gate.py \
  --result "$eval_dir/result.json" \
  --audit "$eval_dir/audit.json" \
  --output "$eval_dir/grade.json"
~~~

Expected: exit 0 only for score at least 90 and zero hard failures.

- [ ] **Step 3: Independently challenge the private result**

Give a separate read-only reviewer only the closed report, typed ledger, packet
audit, approved acceptance gates, and evaluation commit. Require a structured
verdict covering unsupported claims, missed families, weak/duplicate
recommendations, missed reciprocal credit, and privacy. The reviewer cannot
edit or resubmit proposals.

- [ ] **Step 4: Turn each genuine miss into a safe failing fixture**

Create one invented minimal fingerprint and one named test per miss. Run the
test alone to observe failure, make the smallest correction, and run the
affected file to green. Before each commit, search the diff for founder/private
identities, paths, URLs, and copied prose.

~~~bash
git add tests/fixtures/evals tests src/capability_exchange
git commit -m "fix: close a Lens Wow Gate coverage miss"
~~~

- [ ] **Step 5: Repeat twice from clean state and run a holdout**

Create a new private checkout and repeat Steps 1–3. Require two consecutive
passing no-help runs, then run the unseen synthetic holdout. Record publicly
only aggregate score dimensions, counts, hard-failure count, review verdict,
and clean/private-leak checks.

## Task 12: Full verification, independent review, and draft handoff

**Files:**

- Modify this plan only to check boxes and add non-private aggregate evidence
- Update the existing Mission Control card in its isolated worktree
- Update Lens draft PR #53 and Core draft PR #689 only if Core changed

- [ ] **Step 1: Run all Lens verification**

~~~bash
python3 -m ruff check .
python3 scripts/check_inventory.py
python3 scripts/export_catalogue_schema.py
python3 scripts/generate_capability_reference.py
git diff --exit-code -- schemas docs/capability-reference.md
python3 -m pytest -q
git diff --check
~~~

Expected: Ruff, inventory, generators, full pytest, generated equality, and
whitespace checks pass. Environment-gated skips print reasons and retain their
privileged CI proof.

- [ ] **Step 2: Re-verify Core contract stability**

If Core did not change, prove PR #689 remains green and record that no
catalogue update was required. If the exported catalogue schema changed,
vendor only that exact generated schema on the existing isolated Core branch
and run both catalogue generators, exact example comparison, focused Lens
tests, Ruff, and the full Core Python suite before updating PR #689.

- [ ] **Step 3: Run two independent reviews**

One reviewer checks the cumulative Lens diff against the approved spec,
security boundaries, and repository conventions. A different reviewer checks
the private report against its ledger/audit without changes. Resolve every
high/medium finding test-first; explicitly fix or accept low findings.

- [ ] **Step 4: Preflight, push, and watch GitHub**

~~~bash
getent hosts github.com
gh auth status --hostname github.com
gh api user --hostname github.com --jq '"GITHUB_OK: @" + .login'
git ls-remote origin HEAD
git push origin HEAD
gh pr checks 53 --repo davekilleen/dex-lens --watch
~~~

Expected: preflight passes and every required Lens check succeeds. Repeat for
Core only if Core changed.

- [ ] **Step 5: Reconcile durable records without claiming shipment**

Update Mission Control with branch heads, draft PRs, full checks, aggregate
private grade, two no-help passes, sceptical verdict, and publication hold.
Log one Dispatch milestone and publish it. Verify both records and worktrees.

- [ ] **Step 6: Close only at the draft boundary**

Check every completed box, add the final non-private evidence summary, commit
and push, and verify PR checks again. Report “green draft PRs”, never merged,
released, published, deployed, or live.

## Completion proof

This plan is complete only when:

- the private no-help run has zero manual/evaluator conclusions;
- all fourteen significant outcome areas are assessed;
- the engine reconstructs evidence-bound workflows;
- up to ten recommendations are eligible and deterministically ranked without
  padding;
- strengths, reciprocal lessons, and useful surprises are evidence-bound;
- two clean runs score at least 90/100 with no hard failure;
- independent report and code reviews pass;
- Lens and any affected Core checks are green locally and on GitHub;
- private source and output remain unexposed; and
- delivery stops at green draft PRs.
