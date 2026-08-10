# M4 Adaptation Transaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement one bounded, user-owned, reversible Claude Code adaptation through a host-neutral T1–T9 transaction engine and concierge stages 7–8.

**Architecture:** Mutation code lives in a new `adaptation` package, never on the diagnosis adapter surface. The first operation is a create-only, namespaced plain-text Claude Code skill file under an explicitly approved user root; its verifier checks the exact approved bytes and a Success Contract observable signal. Every transaction binds preview, single-use approval, recovery, apply, receipt, verification, and undo through immutable digests and fails closed.

**Tech Stack:** Python, Pydantic, filesystem primitives, pytest fault injection, existing G2/R2/G6 models and concierge server.

---

### Task 1: Closed operation and mutation contracts

**Files:**
- Create: `src/capability_exchange/adaptation/__init__.py`
- Create: `src/capability_exchange/adaptation/contract.py`
- Create: `src/capability_exchange/adaptation/allowlist.py`
- Modify: `src/capability_exchange/adapter/contract.py`
- Test: `tests/adaptation/test_contract.py`
- Test: `tests/adaptation/test_allowlist.py`

- [ ] Write failing tests proving unknown operations, blocked categories, wildcard targets, paths outside approval, and missing guarantees are unconstructable.
- [ ] Run the tests and confirm import/model failures are caused by missing M4 types.
- [ ] Add frozen `MutationContract`, `OperationRecipe`, and guarantee-matrix models plus a data-driven registry containing only `create_namespaced_skill`.
- [ ] Keep Diagnose-only as the default; an Adapt-capable reference validates only when preview, recovery, ownership, receipt, verifier, and undo guarantees are all proven.
- [ ] Re-run the focused tests and existing adapter surface tests.

### Task 2: Preview and single-use approval

**Files:**
- Create: `src/capability_exchange/adaptation/preview.py`
- Create: `src/capability_exchange/adaptation/approval.py`
- Test: `tests/adaptation/test_preview.py`
- Test: `tests/adaptation/test_approval.py`

- [ ] Write failing tests for exact effect lists, canonical target jail, current-byte hash, deterministic preview digest, drift refusal, glob refusal, expiry, replay, wrong-job, and wrong-preview approval.
- [ ] Run and observe the expected missing-feature failures.
- [ ] Implement immutable preview and approval records. Consume approvals atomically and bind them to host, job, capability, target, limits, and preview digest.
- [ ] Re-run focused tests green.

### Task 3: Recovery, receipt, and verification

**Files:**
- Create: `src/capability_exchange/adaptation/recovery.py`
- Create: `src/capability_exchange/adaptation/receipt.py`
- Create: `src/capability_exchange/adaptation/verification.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`
- Test: `tests/adaptation/test_recovery.py`
- Test: `tests/adaptation/test_receipt.py`
- Test: `tests/adaptation/test_verification.py`

- [ ] Write failing tests for restorable backup validation, full/unwritable/truncated backup refusal, private-value-free receipts, product-uninstall readability, and sabotaged verification mapping to `Unknown` + `UNVERIFIED`.
- [ ] Run and confirm red.
- [ ] Implement a user-controlled recovery directory with byte manifest and test-restore, an inventoried durable JSON receipt, and a verifier protocol with exactly Working/Partial/Not demonstrated/Unknown.
- [ ] Register deletion paths and ensure canary source strings cannot serialize into receipts.
- [ ] Re-run focused tests and inventory check.

### Task 4: Transaction, fault recovery, and undo

**Files:**
- Create: `src/capability_exchange/adaptation/transaction.py`
- Create: `src/capability_exchange/adaptation/undo.py`
- Create: `src/capability_exchange/adaptation/incidents.py`
- Test: `tests/adaptation/test_transaction.py`
- Test: `tests/adaptation/test_transaction_faults.py`
- Test: `tests/adaptation/test_undo.py`

- [ ] Write failing tests that kill before backup, mid-write, before commit, and after commit-before-receipt; restart must yield exact pre-state or completed+receipted state.
- [ ] Add failing tests for idempotent replay, same-file conflict, unrelated-work preservation, missing recovery, double undo, and session hard-stop after `Recovery failed`.
- [ ] Implement the journaled state machine and atomic file replacement. Make reconciliation run before any new transaction.
- [ ] Implement bounded undo with conflict reporting and incident/hard-stop events.
- [ ] Run all transaction tests green.

### Task 5: Claude Code operation and T1–T9 conformance

**Files:**
- Create: `src/capability_exchange/adaptation/hosts/claude_code.py`
- Modify: `src/capability_exchange/adapters/claude_code/contract.py`
- Modify: `src/capability_exchange/conformance/checks.py`
- Modify: `src/capability_exchange/conformance/runner.py`
- Test: `tests/adapters/claude_code/test_mutation_contract.py`
- Test: `tests/conformance/test_adaptation_conformance.py`
- Test: `tests/fixtures/hostile/test_g3_adaptation.py`

- [ ] Write failing conformance tests for every T1–T9 requirement and G6+G3 independent defense.
- [ ] Implement the create-only namespaced skill recipe, ownership-preserving standard Markdown output, deterministic exact-byte verifier, recovery contract, and refusal matrix.
- [ ] Ensure diagnosis surface import scans remain green and mutators are not model-exposed.
- [ ] Run the focused conformance and hostile suites.

### Task 6: Concierge stages 7–8, runbooks, and egress

**Files:**
- Modify: `src/capability_exchange/concierge/journey.py`
- Modify: `src/capability_exchange/concierge/server.py`
- Modify: `src/capability_exchange/concierge/views.py`
- Create: `docs/runbooks/incident.md`
- Create: `docs/runbooks/hard-stop.md`
- Test: `tests/concierge/test_adaptation_journey.py`
- Test: `tests/egress/test_m4_packet_egress.py`

- [ ] Write failing transition tests for select→preview→approve→apply→receipt→verify→undo and all refusal/hard-stop exits.
- [ ] Extend the controller and views with explicit, one-change-at-a-time stages; never place domain mutation in HTTP handlers.
- [ ] Add runbook trigger assertions for `Unverified` and `Recovery failed`.
- [ ] Drive the full stage 1–8 journey in the network-none packet/DNS/proxy harness; assert no canary or derivation egress.
- [ ] Run M4 focused suites, then the entire suite and lint.

