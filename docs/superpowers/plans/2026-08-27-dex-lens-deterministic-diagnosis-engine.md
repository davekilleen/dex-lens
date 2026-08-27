# Dex Lens Deterministic Diagnosis Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one durable, deterministic diagnosis engine whose facts, stage
transitions and canonical result are identical through the command line and a
local read-only MCP adapter.

**Architecture:** A deep `DeterministicDiagnosisEngine` module sits over the
existing bounded collector, verified catalogue, comparison ledger and report
store. It persists content-bound checkpoints outside inspected roots, accepts
only validated evidence-referenced specialist proposals, and produces a typed
`DiagnosisResult`; the command-line and MCP routes are shallow adapters over
that same interface.

**Tech Stack:** Python 3.11+, Pydantic v2, official MCP Python SDK v2, pytest,
Hypothesis, Ruff, existing Lens containment/egress/release gates

---

## Delivery boundaries

- Work only in isolated worktrees for `dex-lens`; never edit a shared checkout.
- This plan builds a release candidate. It does not merge, release, register
  the MCP server in user configuration, alter the public installer or invite
  beta testers.
- The existing contained collector and local consent UI remain the only
  authority that can approve a filesystem scope.
- Diagnosis remains read-only. No module under `diagnosis/` may import
  `capability_exchange.adaptation`, `capability_exchange.contribution` or
  `capability_exchange.share`.
- Commit the synthetic replay only. Never commit the supplied transcript, its
  session URL, real names, absolute paths or private excerpts.

## File map

### New Lens files

- `src/capability_exchange/diagnosis/provenance.py` — source classes and
  non-raw source identity.
- `src/capability_exchange/diagnosis/report.py` — ledger-derived report model,
  canonical factual blocks and reconciliation.
- `src/capability_exchange/diagnosis/receipts.py` — local decision/share-state
  receipt types; no sending implementation.
- `src/capability_exchange/diagnosis/run.py` — immutable run input, stages,
  checkpoints and typed public views.
- `src/capability_exchange/concierge/consent.py` — the local user-facing
  authority that alone can issue an approved-scope receipt.
- `src/capability_exchange/diagnosis/run_store.py` — guarded atomic checkpoint
  persistence outside approved roots.
- `src/capability_exchange/diagnosis/specialists.py` — bounded proposal shards
  and deterministic validation.
- `src/capability_exchange/diagnosis/orchestrator.py` — the deep engine
  interface and lawful transitions.
- `src/capability_exchange/diagnosis/cli.py` — JSON command-line adapter.
- `src/capability_exchange/diagnosis/mcp_server.py` — MCP v2 stdio adapter.
- `src/capability_exchange/evaluation/replay.py` — adapter-neutral replay and
  canonical-result comparison.
- `tests/evals/real_session_fixture.py` — invented replay relationships.
- `tests/fixtures/evals/real-session-expected.json` — expected identities,
  state transitions and hard failures.
- Focused tests mirroring each new source module.

### Existing Lens files modified

- `src/capability_exchange/diagnosis/observations.py` — add provenance and make
  observation uniqueness source-aware.
- `src/capability_exchange/diagnosis/comparison.py` — expose only derived
  ledger summaries.
- `src/capability_exchange/adapters/claude_code/discovery.py` — attach source
  provenance before folding.
- `src/capability_exchange/adapters/claude_code/inventory_cli.py` — render
  separate roots and ownership classes.
- `src/capability_exchange/reports/cli.py` — check/save typed results rather
  than unrelated Markdown and JSON files.
- `src/capability_exchange/reports/store.py` — save canonical result artifacts
  and retain backwards-compatible report listing.
- `src/capability_exchange/concierge/cli.py` — dispatch `diagnosis`.
- `src/capability_exchange/concierge/server.py` — hand an authenticated local
  approval to the consent authority without giving CLI/MCP that authority.
- `src/capability_exchange/skill/dex-lens/SKILL.md` — guide the engine instead
  of owning the checklist.
- `src/capability_exchange/boundary/data_inventory.yaml` — declare every new
  retained field and its privacy class.
- `pyproject.toml` — add MCP dependency, `dex-lens-mcp` entry point and package
  test coverage.

## Workstream A — make false completeness impossible

### Task 1: Lock the real-session failure into a sanitised red evaluation

**Files:**
- Create: `tests/evals/real_session_fixture.py`
- Create: `tests/fixtures/evals/real-session-expected.json`
- Create: `tests/evals/test_real_session_replay.py`
- Modify: `src/capability_exchange/evaluation/diagnosis.py`

- [ ] **Step 1: Write the invented 115-entry disposition fixture**

Create a builder that uses only synthetic identities and the observed count
relationship:

```python
from collections import Counter

from capability_exchange.diagnosis.comparison import Disposition

EXPECTED_COUNTS = Counter(
    {
        Disposition.NOT_ASSESSED: 80,
        Disposition.NOT_RELEVANT: 17,
        Disposition.SHARED: 8,
        Disposition.WORTH_BORROWING: 3,
        Disposition.FRAGILE_OR_CONTRADICTORY: 3,
        Disposition.STRONG_HERE: 2,
        Disposition.DEX_SHOULD_LEARN: 2,
    }
)


def synthetic_entry_ids() -> tuple[str, ...]:
    return tuple(f"invented-capability-{index:03d}" for index in range(115))
```

Assign those identities deterministically in enum/count order. Use
`probe-token:` and `file-token:` evidence references only; include one
same-name pair from `vault-authored` and `user-global` sources and the canary
`INVENTED_SESSION_CANARY_NEVER_RETAIN` in an input secret field.

- [ ] **Step 2: Write the failing report/ledger reconciliation test**

```python
def test_report_cannot_claim_93_covered_when_80_are_not_assessed() -> None:
    ledger = real_session_ledger()
    report = real_session_report().replace(
        "80 capabilities remain Unknown",
        "93 capabilities are already covered",
    )

    result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=report,
        expected=expected_contract(),
    )

    assert not result.passed
    assert any("ledger-derived facts" in item for item in result.report_errors)
```

- [ ] **Step 3: Run the new test and prove the current gate is wrong**

Run:

```bash
.venv/bin/python -m pytest tests/evals/test_real_session_replay.py -q
```

Expected: FAIL because the current report evaluator does not reconcile factual
coverage claims with the ledger.

- [ ] **Step 4: Add the expected replay contract**

Write exact JSON fields for `catalogue_entry_count: 115`, the seven
disposition counts, expected stage order, forbidden claim
`93 capabilities are already covered`, required provenance classes, and
required clean-close fields. Load it with the same strict mapping checks used
by `tests/evals/test_legacy_system_diagnosis.py`.

- [ ] **Step 5: Commit the red evaluation**

```bash
git add tests/evals/real_session_fixture.py \
  tests/evals/test_real_session_replay.py \
  tests/fixtures/evals/real-session-expected.json
git commit -m "test: capture Lens false completeness replay"
```

### Task 2: Preserve provenance across every approved root

**Files:**
- Create: `src/capability_exchange/diagnosis/provenance.py`
- Create: `tests/diagnosis/test_provenance.py`
- Modify: `src/capability_exchange/diagnosis/observations.py`
- Modify: `src/capability_exchange/adapters/claude_code/discovery.py`
- Modify: `tests/adapters/claude_code/test_discovery.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`

- [ ] **Step 1: Write failing source-aware uniqueness tests**

```python
def test_same_identity_from_two_sources_is_not_collapsed() -> None:
    vault = provenance("vault", SourceClass.VAULT_AUTHORED)
    global_home = provenance("global", SourceClass.USER_GLOBAL)
    fingerprint = EvidenceFingerprint(
        adapter_id="claude-code-local",
        collected_at=NOW,
        observations=(skill("planner", vault), skill("planner", global_home)),
    )

    assert [item.provenance.source_id for item in fingerprint.observations] == [
        "scope:vault",
        "scope:global",
    ]
```

Add a companion test that duplicate `(kind, identity, source_id)` values are
rejected and a test that raw absolute paths and secret-shaped values are
refused.

- [ ] **Step 2: Run the provenance tests red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_provenance.py -q
```

Expected: FAIL because `Observation` has no provenance and fingerprint
uniqueness currently uses only `(kind, identity)`.

- [ ] **Step 3: Add the closed provenance models**

Implement:

```python
class SourceClass(StrEnum):
    VAULT_AUTHORED = "vault-authored"
    USER_GLOBAL = "user-global"
    HARNESS_BUNDLED = "harness-bundled"
    PLUGIN_OR_VENDOR = "plugin-or-vendor"
    WORKING_COPY = "working-copy"
    GENERATED = "generated"
    LIVE_SYSTEM = "live-system"


class SourceProvenance(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(pattern=r"^scope:[a-z0-9._-]{3,120}$")
    source_class: SourceClass
    scope_reference: str = Field(pattern=r"^scope:sha256:[0-9a-f]{64}$")
    relative_reference: str = Field(min_length=1, max_length=240)
    content_digest: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
```

Validators reject leading `/`, home prefixes, `..`, control characters and
secret-shaped markers in `relative_reference`.

- [ ] **Step 4: Attach provenance before discovery groups observations**

Extend the discovery input with source descriptors derived from the consent
snapshot. Emit separate observations for same-name items across source IDs.
Classify working-copy paths as `WORKING_COPY`; they may render housekeeping
but must not prove an active capability.

- [ ] **Step 5: Update the privacy inventory and pass focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_provenance.py \
  tests/diagnosis/test_observations.py \
  tests/adapters/claude_code/test_discovery.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit provenance**

```bash
git add src/capability_exchange/diagnosis/provenance.py \
  src/capability_exchange/diagnosis/observations.py \
  src/capability_exchange/adapters/claude_code/discovery.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_provenance.py \
  tests/diagnosis/test_observations.py \
  tests/adapters/claude_code/test_discovery.py
git commit -m "feat: preserve diagnosis source provenance"
```

### Task 3: Make the report a typed projection of the ledger

**Files:**
- Create: `src/capability_exchange/diagnosis/report.py`
- Create: `tests/diagnosis/test_report_model.py`
- Modify: `src/capability_exchange/diagnosis/comparison.py`
- Modify: `src/capability_exchange/evaluation/diagnosis.py`

- [ ] **Step 1: Write failing derived-summary tests**

```python
def test_summary_is_derived_from_entries() -> None:
    ledger = real_session_ledger()
    summary = LedgerSummary.from_ledger(ledger)

    assert summary.total == 115
    assert summary.unknown == 80
    assert summary.assessed == 35
    assert summary.by_disposition[Disposition.SHARED] == 8


def test_report_model_rejects_unrelated_ledger_digest() -> None:
    with pytest.raises(ValueError, match="exact comparison ledger"):
        ReportModel.from_result(
            run_identity=run_identity(),
            ledger=real_session_ledger(),
            ledger_sha256="0" * 64,
            findings=(),
        )
```

- [ ] **Step 2: Run the new report-model tests red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_report_model.py -q
```

Expected: FAIL because no typed report model exists.

- [ ] **Step 3: Implement derived summary and canonical fact block**

Use a private constructor and one public factory:

```python
class LedgerSummary(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(ge=1)
    by_disposition: dict[Disposition, int]
    assessed: int = Field(ge=0)
    unknown: int = Field(ge=0)

    @classmethod
    def from_ledger(cls, ledger: ComparisonLedger) -> Self:
        counts = Counter(item.disposition for item in ledger.entries)
        unknown = counts[Disposition.NOT_ASSESSED]
        return cls(
            total=len(ledger.entries),
            by_disposition={item: counts[item] for item in Disposition},
            assessed=len(ledger.entries) - unknown,
            unknown=unknown,
        )

    def canonical_markdown(self) -> str:
        return (
            f"- Catalogue accounting: {self.total} entries; "
            f"{self.assessed} assessed; {self.unknown} remain Unknown.\n"
            + "- Dispositions: "
            + ", ".join(
                f"{item.value}={self.by_disposition[item]}" for item in Disposition
            )
            + ".\n"
        )
```

`ReportModel` carries grounded finding tuples, limits, receipts and the exact
ledger digest. Its `render_markdown()` inserts `canonical_markdown()` under
Coverage and limits.

- [ ] **Step 4: Make evaluation compare the exact canonical block**

Add `canonical_fact_block` to `_report_errors`. Reject reports that omit it,
alter it or include a conflicting coverage-number sentence elsewhere.

- [ ] **Step 5: Pass the red replay**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_report_model.py \
  tests/evals/test_real_session_replay.py \
  tests/evals/test_legacy_system_diagnosis.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit typed report truth**

```bash
git add src/capability_exchange/diagnosis/report.py \
  src/capability_exchange/diagnosis/comparison.py \
  src/capability_exchange/evaluation/diagnosis.py \
  tests/diagnosis/test_report_model.py \
  tests/evals/test_real_session_replay.py
git commit -m "fix: derive Lens report facts from its ledger"
```

### Task 4: Require decision and share receipts for completion claims

**Files:**
- Create: `src/capability_exchange/diagnosis/receipts.py`
- Create: `tests/diagnosis/test_receipts.py`
- Modify: `src/capability_exchange/diagnosis/report.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`

- [ ] **Step 1: Write failing state-integrity tests**

```python
def test_preview_is_not_shared() -> None:
    receipt = ShareReceipt.preview(
        disclosure_sha256="a" * 64,
        created_at=NOW,
    )
    assert receipt.state is ShareState.PREVIEWED
    assert not receipt.was_sent


def test_taken_requires_a_local_decision_receipt() -> None:
    with pytest.raises(ValueError, match="decision receipt"):
        RecommendationDecision(
            catalogue_id="invented-capability-001",
            state=DecisionState.CHOSEN,
            receipt=None,
        )
```

- [ ] **Step 2: Run receipt tests red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_receipts.py -q
```

Expected: FAIL because report decisions are currently free-form prose.

- [ ] **Step 3: Add closed receipt types**

Implement `DecisionState` as `offered`, `chosen`, `completed`; implement
`ShareState` as `not-offered`, `offered`, `previewed`, `sent`. Receipts are
frozen, extra-forbid models containing a run ID, catalogue ID or disclosure
digest, UTC time and a local consent-surface receipt ID. `sent` additionally
requires a bounded destination class and response receipt digest.

- [ ] **Step 4: Render decisions and sharing only from receipts**

`ReportModel.render_markdown()` derives “What you decided” and the close from
receipt objects. Remove any input field that accepts pre-rendered decision or
share prose.

- [ ] **Step 5: Pass focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_receipts.py \
  tests/diagnosis/test_report_model.py -q
```

Expected: PASS.

```bash
git add src/capability_exchange/diagnosis/receipts.py \
  src/capability_exchange/diagnosis/report.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_receipts.py \
  tests/diagnosis/test_report_model.py
git commit -m "feat: bind Lens decisions and sharing to receipts"
```

## Workstream B — durable deterministic orchestration

### Task 5: Add immutable run identity and a closed stage machine

**Files:**
- Create: `src/capability_exchange/diagnosis/run.py`
- Create: `src/capability_exchange/concierge/consent.py`
- Create: `tests/diagnosis/test_run.py`
- Create: `tests/concierge/test_diagnosis_consent.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`

- [ ] **Step 1: Write failing stage and drift tests**

```python
def test_stage_order_is_closed() -> None:
    assert list(DiagnosisStage) == [
        DiagnosisStage.CREATED,
        DiagnosisStage.SCOPE_APPROVED,
        DiagnosisStage.CAPTURED,
        DiagnosisStage.CATALOGUE_VERIFIED,
        DiagnosisStage.JOBS_CONFIRMED,
        DiagnosisStage.COMPARED,
        DiagnosisStage.RENDERED,
        DiagnosisStage.CHECKED,
        DiagnosisStage.SAVED,
        DiagnosisStage.CLOSED,
    ]


def test_input_identity_changes_when_scope_changes() -> None:
    assert diagnosis_input(scope="a").identity_digest != diagnosis_input(
        scope="b"
    ).identity_digest


def test_only_local_consent_authority_can_issue_scope_receipt() -> None:
    authority = LocalScopeConsentAuthority(storage=private_storage())
    request = authority.prepare(candidate_roots=(invented_root(),))
    assert authority.receipt_for(request.run_id) is None
    receipt = authority.approve_from_local_session(
        run_id=request.run_id,
        scope_snapshot=approved_scope_snapshot(),
        authenticated_session_id="local-session",
    )
    assert receipt.run_id == request.run_id
```

- [ ] **Step 2: Run the stage tests red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_run.py -q
```

Expected: FAIL because the durable run contract does not exist.

- [ ] **Step 3: Implement run models**

Create `ApprovedScopeReceipt`, `DiagnosisStage`, `RunIdentity`,
`DiagnosisInput`, `DiagnosisCheckpoint` and `DiagnosisRunView` as frozen
extra-forbid models. The receipt contains the run ID, non-raw scope
references, exact scope digest, local session receipt ID and aware approval
time. Canonically serialise with `dump_for_storage()`, SHA-256 the sorted
compact JSON bytes and reject naive timestamps. `DiagnosisCheckpoint` stores
current stage, previous digest, input identity, completed-artifact digests and
a bounded next-action string.

- [ ] **Step 4: Implement lawful transition validation**

Use one mapping:

```python
NEXT_STAGE = {
    DiagnosisStage.CREATED: DiagnosisStage.SCOPE_APPROVED,
    DiagnosisStage.SCOPE_APPROVED: DiagnosisStage.CAPTURED,
    DiagnosisStage.CAPTURED: DiagnosisStage.CATALOGUE_VERIFIED,
    DiagnosisStage.CATALOGUE_VERIFIED: DiagnosisStage.JOBS_CONFIRMED,
    DiagnosisStage.JOBS_CONFIRMED: DiagnosisStage.COMPARED,
    DiagnosisStage.COMPARED: DiagnosisStage.RENDERED,
    DiagnosisStage.RENDERED: DiagnosisStage.CHECKED,
    DiagnosisStage.CHECKED: DiagnosisStage.SAVED,
    DiagnosisStage.SAVED: DiagnosisStage.CLOSED,
}
```

`advance_to()` accepts only `NEXT_STAGE[current]`; re-requesting the current
stage returns the same checkpoint; skipping or moving backwards raises
`DiagnosisStateError`.

`LocalScopeConsentAuthority.prepare()` may persist only candidate scope
locators and a run ID; it reads nothing. Only the authenticated loopback
consent session calls `approve_from_local_session()`. CLI/MCP receive
`receipt_for()` read access but no approval method.

- [ ] **Step 5: Pass tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_run.py -q
.venv/bin/python -m pytest tests/concierge/test_diagnosis_consent.py -q
```

Expected: PASS.

```bash
git add src/capability_exchange/diagnosis/run.py \
  src/capability_exchange/concierge/consent.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_run.py tests/concierge/test_diagnosis_consent.py
git commit -m "feat: add durable Lens diagnosis stages"
```

### Task 6: Persist checkpoints atomically outside inspected roots

**Files:**
- Create: `src/capability_exchange/diagnosis/run_store.py`
- Create: `tests/diagnosis/test_run_store.py`
- Modify: `src/capability_exchange/catalogue/subscription.py`

- [ ] **Step 1: Write failing storage-boundary and torn-write tests**

```python
def test_run_store_is_outside_every_approved_root(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    with pytest.raises(ValueError, match="outside the approved read scope"):
        DiagnosisRunStore(root / "state", approved_roots=(root,))


def test_failed_replace_leaves_previous_checkpoint(
    store: DiagnosisRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = store.save(checkpoint(DiagnosisStage.CREATED))
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        store.save(checkpoint(DiagnosisStage.SCOPE_APPROVED))
    assert store.load(first.run_id).stage is DiagnosisStage.CREATED
```

- [ ] **Step 2: Run storage tests red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_run_store.py -q
```

Expected: FAIL because no run store exists.

- [ ] **Step 3: Implement guarded atomic save**

Store under `default_lens_app_storage(approved_roots) / "diagnosis-runs"`.
Write canonical JSON to a mode-`0600` sibling temporary file, flush and
`os.fsync`, then `os.replace` the checkpoint path. Reject symlinks, unknown
run IDs, invalid digests and a storage directory inside any approved root.

- [ ] **Step 4: Add resume and stale-input checks**

`load(run_id, expected_input_digest=...)` refuses a mismatch with
`DiagnosisInputDrift`; `list_resumable()` returns only non-terminal valid
checkpoints sorted by creation time.

- [ ] **Step 5: Pass focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_run_store.py \
  tests/catalogue/test_catalogue_cli.py -q
```

Expected: PASS.

```bash
git add src/capability_exchange/diagnosis/run_store.py \
  src/capability_exchange/catalogue/subscription.py \
  tests/diagnosis/test_run_store.py
git commit -m "feat: checkpoint Lens diagnosis runs safely"
```

### Task 7: Add bounded specialist proposals and a sceptical reconciler

**Files:**
- Create: `src/capability_exchange/diagnosis/specialists.py`
- Create: `tests/diagnosis/test_specialists.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`

- [ ] **Step 1: Write failing proposal-authority tests**

```python
def test_proposal_cannot_reference_another_run() -> None:
    with pytest.raises(SpecialistProposalError, match="current fingerprint"):
        validate_proposal(
            proposal(evidence_ids=("foreign:evidence",)),
            context=proposal_context(evidence_ids=("current:evidence",)),
        )


def test_specialist_cannot_recommend_held_capability() -> None:
    with pytest.raises(SpecialistProposalError, match="not available"):
        validate_proposal(
            recommendation("held-capability"),
            context=proposal_context(held_ids=("held-capability",)),
        )
```

- [ ] **Step 2: Run specialist tests red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_specialists.py -q
```

Expected: FAIL because semantic proposals have no typed seam.

- [ ] **Step 3: Implement the closed proposal vocabulary**

Add `SpecialistRole`, `ProposalKind`, `SpecialistShard`,
`SpecialistProposal`, `ProposalContext` and `ValidatedProposal`. Limit each
proposal to eight evidence references, one 600-character reason and identities
from the shard. Validation checks run ID, fingerprint digest, catalogue digest,
availability, source provenance and the three-recommendation cap.

The closed `SpecialistRole` values are `tools-and-integrations`,
`automations-and-live-state`, `strength-and-reciprocal`,
`contradictions-and-reliability`, `release-distance` and
`sceptical-reconciler`. No adapter may invent an additional role string.

- [ ] **Step 4: Implement deterministic disagreement handling**

Group validated proposals by `(kind, catalogue_id, capability_id)`. Matching
proposals coalesce with sorted evidence IDs. Conflicting dispositions become
one `not-assessed` result with the reason “Specialist proposals disagreed; the
comparison remains Unknown.” No confidence score breaks a tie.

- [ ] **Step 5: Pass tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_specialists.py -q
```

Expected: PASS.

```bash
git add src/capability_exchange/diagnosis/specialists.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/diagnosis/test_specialists.py
git commit -m "feat: validate bounded Lens specialist proposals"
```

### Task 8: Implement the deep deterministic engine interface

**Files:**
- Create: `src/capability_exchange/diagnosis/orchestrator.py`
- Create: `tests/diagnosis/test_orchestrator.py`
- Modify: `src/capability_exchange/diagnosis/__init__.py`
- Modify: `src/capability_exchange/reports/store.py`

- [ ] **Step 1: Write failing interface and idempotence tests**

```python
def test_advance_is_idempotent_for_same_checkpoint(engine: EngineHarness) -> None:
    prepared = engine.prepare(prepare_request())
    engine.consent_authority.approve_from_local_session(
        run_id=prepared.run_id,
        scope_snapshot=approved_scope_snapshot(),
        authenticated_session_id="local-session",
    )
    first = engine.advance(prepared.run_id)
    repeated = engine.advance(prepared.run_id)
    assert repeated == first


def test_result_is_unavailable_before_close(engine: EngineHarness) -> None:
    run = engine.prepare(prepare_request())
    with pytest.raises(DiagnosisStateError, match="not closed"):
        engine.result(run.run_id)


def test_advance_cannot_read_before_local_scope_approval(
    engine: EngineHarness,
) -> None:
    run = engine.prepare(prepare_request())
    with pytest.raises(DiagnosisStateError, match="approve the exact scope"):
        engine.advance(run.run_id)
```

Add tests that each stage calls exactly its lawful dependency, failed
reconciliation never reaches `SAVED`, and `CLOSED` exposes no mutation port.

- [ ] **Step 2: Run orchestrator tests red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_orchestrator.py -q
```

Expected: FAIL because no engine interface owns the run.

- [ ] **Step 3: Implement `DeterministicDiagnosisEngine`**

Constructor dependencies are accepted, never created internally:

```python
class DeterministicDiagnosisEngine:
    def __init__(
        self,
        *,
        run_store: DiagnosisRunStore,
        consent_authority: LocalScopeConsentAuthority,
        collector: FingerprintCollector,
        catalogue_loader: VerifiedCatalogueLoader,
        comparer: ComparisonBuilder,
        report_store: LensReportStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._runs = run_store
        self._consent = consent_authority
        self._collector = collector
        self._catalogues = catalogue_loader
        self._compare = comparer
        self._reports = report_store
        self._clock = clock
```

Expose only `prepare`, `status`, `advance`, `submit` and `result` to CLI/MCP.
`prepare` reads nothing and delegates candidate-scope display to the local
consent authority. Each later call loads the checkpoint, validates its digest,
requires the authority's exact receipt where applicable, performs at most one
stage, stores artifacts by digest and returns a non-secret
`DiagnosisRunView`.

- [ ] **Step 4: Make save consume `ReportModel`, not arbitrary Markdown**

Add `LensReportStore.save_result(result, label, now)`; it renders canonical
Markdown internally, saves the ledger and result JSON beside it, and verifies
the three digests before returning. Keep the old `save(markdown)` method only
for reading/listing legacy reports; the new engine never calls it.

- [ ] **Step 5: Pass engine and existing report tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_orchestrator.py \
  tests/reports/test_report_store.py \
  tests/reports/test_reports_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the engine**

```bash
git add src/capability_exchange/diagnosis/orchestrator.py \
  src/capability_exchange/diagnosis/__init__.py \
  src/capability_exchange/reports/store.py \
  tests/diagnosis/test_orchestrator.py \
  tests/reports/test_report_store.py
git commit -m "feat: centralise Lens diagnosis orchestration"
```

## Workstream C — one engine through CLI and MCP

### Task 9: Add the JSON command-line adapter

**Files:**
- Create: `src/capability_exchange/diagnosis/cli.py`
- Create: `tests/diagnosis/test_cli.py`
- Modify: `src/capability_exchange/concierge/cli.py`
- Modify: `src/capability_exchange/concierge/server.py`
- Modify: `tests/concierge/test_cli.py`
- Modify: `tests/concierge/test_local_server.py`

- [ ] **Step 1: Write failing command dispatch and JSON tests**

```python
def test_status_prints_only_canonical_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_engine", lambda: fake_engine(CAPTURED_VIEW))
    assert diagnosis_main(["status", "--run", RUN_ID, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == CAPTURED_VIEW.dump_for_storage()


def test_concierge_dispatches_diagnosis_without_opening_browser(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(concierge_cli, "diagnosis_main", lambda args: called.append(args) or 0)
    assert concierge_cli.main(["diagnosis", "status", "--run", RUN_ID]) == 0
    assert called == [["status", "--run", RUN_ID]]


def test_prepare_reads_nothing_until_local_approval(engine_harness) -> None:
    prepared = engine_harness.cli(["prepare", "--root", str(invented_root())])
    assert prepared.stage == "created"
    assert engine_harness.collector.calls == 0
    engine_harness.approve_in_local_browser(prepared.run_id)
    engine_harness.cli(["advance", "--run", prepared.run_id])
    assert engine_harness.collector.calls == 1
```

- [ ] **Step 2: Run CLI tests red**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_cli.py tests/concierge/test_cli.py -q
```

Expected: FAIL because `diagnosis` is not a subcommand.

- [ ] **Step 3: Implement the command set**

Add argparse subcommands `prepare`, `status`, `advance`, `submit`, `result`.
`prepare` calls `engine.prepare()`, starts the existing local consent surface
and returns run ID plus approval URL; it does not collect. The authenticated
scope-approval POST in `concierge/server.py` calls the authority's
`approve_from_local_session()` with the already captured `ScopeSnapshot`.
JSON goes to stdout, refusals and human guidance to stderr. `result --format
markdown` prints only canonical report Markdown.

- [ ] **Step 4: Prove adapter/core byte equality**

Serialise `engine.result(run_id).dump_for_storage()` with sorted compact JSON
and assert exact bytes equal CLI `result --format json` output.

- [ ] **Step 5: Pass tests and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_cli.py tests/concierge/test_cli.py \
  tests/concierge/test_local_server.py -q
```

Expected: PASS.

```bash
git add src/capability_exchange/diagnosis/cli.py \
  src/capability_exchange/concierge/cli.py \
  src/capability_exchange/concierge/server.py \
  tests/diagnosis/test_cli.py tests/concierge/test_cli.py \
  tests/concierge/test_local_server.py
git commit -m "feat: add deterministic Lens diagnosis commands"
```

### Task 10: Add the thin MCP v2 stdio adapter

**Files:**
- Create: `src/capability_exchange/diagnosis/mcp_server.py`
- Create: `tests/diagnosis/test_mcp_server.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_packaging.py`

- [ ] **Step 1: Pin the stable official SDK line and write a red tool-list test**

Add `mcp>=2,<3` to runtime dependencies and `dex-lens-mcp` to project scripts.
Then write:

```python
EXPECTED_TOOLS = {
    "prepare_diagnosis",
    "get_diagnosis_status",
    "advance_diagnosis",
    "submit_specialist_proposal",
    "get_diagnosis_result",
}


async def test_mcp_exposes_only_the_read_only_diagnosis_tools() -> None:
    server = build_mcp_server(fake_engine())
    async with Client(server) as client:
        tools = await client.list_tools()
    assert {item.name for item in tools.tools} == EXPECTED_TOOLS
```

- [ ] **Step 2: Run the MCP test red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_mcp_server.py -q
```

Expected: FAIL because the server and dependency do not exist.

- [ ] **Step 3: Implement the MCP adapter**

Use the official v2 interface:

```python
from mcp.server import MCPServer


def build_mcp_server(engine: DeterministicDiagnosisEngine) -> MCPServer:
    server = MCPServer("dex-lens-diagnosis")

    @server.tool()
    def get_diagnosis_status(run_id: str) -> dict[str, object]:
        """Return proved stages and the next required action for one local run."""
        return engine.status(run_id).dump_for_storage()

    @server.tool()
    def advance_diagnosis(run_id: str) -> dict[str, object]:
        """Perform one lawful read-only diagnosis transition."""
        return engine.advance(run_id).dump_for_storage()

    register_prepare_tool(server, engine)
    register_proposal_tool(server, engine)
    register_result_tool(server, engine)
    return server


def main() -> None:
    build_mcp_server(build_engine()).run(transport="stdio")
```

Registration helpers contain translation only; they call the same engine
methods and return `dump_for_storage()`.

- [ ] **Step 4: Add hostile MCP-wire tests**

Assert stdout contains protocol only; secret canaries, absolute paths and
unknown Pydantic fields are refused; no tool name contains `write`, `delete`,
`install`, `repair`, `share` or `send`; and calling `advance` before a consent
receipt returns a structured tool error without collection.

- [ ] **Step 5: Prove direct/CLI/MCP byte equality**

For one closed synthetic run, compare sorted compact JSON bytes from direct
engine result, CLI result and `get_diagnosis_result`. Require exact equality.

- [ ] **Step 6: Pass packaging and MCP tests, then commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_mcp_server.py \
  tests/diagnosis/test_cli.py \
  tests/test_packaging.py -q
```

Expected: PASS.

```bash
git add pyproject.toml \
  src/capability_exchange/diagnosis/mcp_server.py \
  tests/diagnosis/test_mcp_server.py tests/test_packaging.py
git commit -m "feat: expose Lens diagnosis through read-only MCP"
```

### Task 11: Move the skill from orchestration to explanation

**Files:**
- Modify: `src/capability_exchange/skill/dex-lens/SKILL.md`
- Modify: `tests/test_skill_complete_diagnosis.py`
- Create: `tests/test_skill_deterministic_engine.py`

- [ ] **Step 1: Write failing skill-contract tests**

```python
def test_skill_uses_engine_status_instead_of_keeping_its_own_checklist() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "dex-lens diagnosis status" in text
    assert "Do not calculate or rewrite catalogue totals" in text
    assert "A diagnosis ends only when the engine returns `closed`" in text


def test_skill_keeps_repairs_and_sharing_outside_diagnosis() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "start a separate, explicitly approved flow" in text
    assert "A preview is not a share receipt" in text
```

- [ ] **Step 2: Run the skill tests red**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_skill_complete_diagnosis.py \
  tests/test_skill_deterministic_engine.py -q
```

Expected: FAIL because the current skill still owns manual ledger/report flow.

- [ ] **Step 3: Rewrite only the orchestration passages**

Keep the consent language, lay explanations, praise bar, two-way comparison
rubric and read-only promise. Replace manual count/check/save instructions with
engine `status`, `advance`, `submit` and `result` calls. Require the generated
close fields and prohibit continuation into repair inside the diagnosis run.

- [ ] **Step 4: Prove the skill and engine close agree**

Add assertions that the skill names every generated close field from
`ReportModel` and does not contain independent numeric coverage examples.

- [ ] **Step 5: Pass tests and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_skill_complete_diagnosis.py \
  tests/test_skill_report_template.py \
  tests/test_skill_deterministic_engine.py -q
```

Expected: PASS.

```bash
git add src/capability_exchange/skill/dex-lens/SKILL.md \
  tests/test_skill_complete_diagnosis.py \
  tests/test_skill_deterministic_engine.py
git commit -m "docs: make the Lens skill follow engine truth"
```

## Workstream D — replay, containment and review

### Task 12: Run the golden replay through every adapter

**Files:**
- Create: `src/capability_exchange/evaluation/replay.py`
- Modify: `tests/evals/test_real_session_replay.py`
- Create: `tests/evals/test_adapter_conformance.py`
- Create: `tests/evals/test_interrupted_run.py`
- Modify: `tests/adapters/claude_code/test_surface_read_only.py`

- [ ] **Step 1: Add canonical replay helpers**

Implement `run_direct`, `run_cli` and `run_mcp` helpers that accept the same
sanitised input and proposal tuple and return canonical result bytes. They may
vary transport only; they do not construct different engine inputs.

- [ ] **Step 2: Add equality and order-invariance tests**

```python
@pytest.mark.parametrize("ordering", ["forward", "reverse", "rotated"])
def test_canonical_result_is_transport_and_order_invariant(ordering: str) -> None:
    replay = real_session_replay(ordering=ordering)
    outputs = {
        run_direct(replay),
        run_cli(replay),
        run_mcp(replay),
    }
    assert len(outputs) == 1
```

Use a fixed clock. Preserve source order only where it is meaningful; sort
sets by closed identity keys before serialisation.

Add fake Claude-style and Codex-style callers that discover the MCP tools in a
different order and still obtain the same canonical result bytes.

- [ ] **Step 3: Add interruption tests at every stage**

For every non-terminal stage, stop after checkpoint, rebuild the engine over
the same store, resume and compare the final bytes with an uninterrupted run.
Change one scope digest and assert the resumed run is refused as stale.

- [ ] **Step 4: Add hostile factual mutation tests**

Mutate one count, catalogue hash, evidence reference, decision state, share
state and source class in turn. Each mutation must fail before `SAVED` and
leave the previous checkpoint intact.

Extend `test_surface_read_only.py` to walk imports beneath
`capability_exchange.diagnosis` and fail if they reach adaptation,
contribution, sharing, subprocess execution or a generic network client.

- [ ] **Step 5: Pass replay tests and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/evals/test_real_session_replay.py \
  tests/evals/test_adapter_conformance.py \
  tests/evals/test_interrupted_run.py -q
.venv/bin/python -m pytest \
  tests/adapters/claude_code/test_surface_read_only.py -q
```

Expected: PASS.

```bash
git add src/capability_exchange/evaluation/replay.py \
  tests/evals/test_real_session_replay.py \
  tests/evals/test_adapter_conformance.py \
  tests/evals/test_interrupted_run.py \
  tests/adapters/claude_code/test_surface_read_only.py
git commit -m "test: replay Lens diagnosis across CLI and MCP"
```

### Task 13: Prove the complete Lens candidate without publishing it

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/superpowers/specs/2026-08-27-dex-lens-deterministic-diagnosis-engine-design.md`

- [ ] **Step 1: Run focused diagnosis and report tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis tests/reports tests/evals \
  tests/test_skill_complete_diagnosis.py \
  tests/test_skill_report_template.py \
  tests/test_skill_deterministic_engine.py -q
```

Expected: PASS with no unexpected skips.

- [ ] **Step 2: Run containment, egress and packaging gates**

Run:

```bash
.venv/bin/python -m pytest \
  tests/adapters tests/egress \
  tests/test_packaging.py -q
```

Expected: PASS; every environment-gated skip prints its reason.

- [ ] **Step 3: Run the full Lens suite and lint**

Run:

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check src tests
```

Expected: PASS and Ruff clean.

- [ ] **Step 4: Run privacy and architecture scans**

Run the repository's current PII/founder-content, data-inventory, dependency,
read-only-surface and release-manifest checks exactly as CI defines them. Also
run:

```bash
git grep -nE '/Users/[A-Za-z]|/home/[A-Za-z]|session_[A-Za-z0-9]+' -- \
  src tests docs \
  ':!docs/superpowers/plans/2026-08-27-dex-lens-deterministic-diagnosis-engine.md'
```

Expected: no real path or session URL. The invented canary may exist only as a
test input; the replay tests assert it is absent from fingerprints,
checkpoints, reports and MCP messages.

- [ ] **Step 5: Update status truth and commit**

State that the engine candidate is implemented and locally verified but not
merged, released, registered or live. Record exact test counts and any
environment-gated skips.

```bash
git add docs/STATUS.md \
  docs/superpowers/specs/2026-08-27-dex-lens-deterministic-diagnosis-engine-design.md
git commit -m "docs: record deterministic diagnosis candidate truth"
```

- [ ] **Step 6: Push a review branch and open a draft PR**

Perform the runner-local GitHub preflight, push the feature branch, open a
draft PR and monitor its checks. Do not merge or release. The PR body must link
the design, this plan, the Mission Control card and the exact golden-replay
proof.

## Final completion proof

The implementation plan is complete only when:

1. the real-session replay rejects the historical false-coverage report;
2. report facts and ledger counts share one source of truth;
3. cross-root same-name items retain provenance and cannot silently merge;
4. decision and share completion require receipts;
5. every run transition is persisted atomically and resumes exactly;
6. optional specialist proposals can improve judgement without acquiring
   authority over evidence or state;
7. direct engine, CLI and MCP results are byte-identical for the same input;
8. diagnosis exposes no mutation or send tool;
9. focused, full, lint, packaging, containment, egress and privacy checks pass;
10. the candidate sits in a green draft PR with honest Mission Control and
    Dispatch state; and
11. no merge, release, installer registration or beta publication has happened
    without Dave's later explicit approval.
