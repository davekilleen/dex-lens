# Dex Lens deterministic diagnosis engine — Cursor Cloud handoff

## Start here

- Repository: `davekilleen/dex-lens`
- Continue branch: `codex/lens-deterministic-diagnosis-engine-build`
- Checkpoint commit before this handoff: `203e50046d89d8798edc4f2b6734382fe2d7ac32`
- Approved design: `docs/superpowers/specs/2026-08-27-dex-lens-deterministic-diagnosis-engine-design.md`
- Implementation plan: `docs/superpowers/plans/2026-08-27-dex-lens-deterministic-diagnosis-engine.md`
- Design PR: https://github.com/davekilleen/dex-lens/pull/45
- Implementation PR: https://github.com/davekilleen/dex-lens/pull/46
- Mission Control card PR: https://github.com/davekilleen/dex-cards/pull/99

This is a clean continuation point, not a restart. Do not merge, publish, release,
or change the live installer. The current public release remains Dex Lens v0.1.12.

## What is complete

### Task 1 — real-session false-completeness evaluation

Commits `c71dc84` and `756e4a9` add a sanitised replay derived from the supplied
session. It checks the failure that motivated this work: Lens must not claim that
the comparison is complete when evidence has been dropped or invented.

### Task 2 — provenance across every approved root

Commits `5b8ff1b`, `8ff5586`, `36ecc66`, and `203e500` preserve source identity from
collection through observations and the comparison ledger. The public boundary was
hardened against forged paths, path-like aliases, secret-bearing provenance, and
untrusted construction paths.

Verification at the checkpoint:

- Focused suite: 514 passed, 1 macOS-only skip.
- Full suite excluding the deliberately red replay assertion: 2,011 passed,
  15 documented environment/platform skips, 0 failures.
- The replay test fails only at `assert not result.passed`. This is intentional:
  Task 3 must add reconciliation and turn it green.
- Ruff, inventory validation, and `git diff --check` are green.
- Inventory: 678 fields; 113 stored with deletion paths; 1 transmitted through
  closed, reviewed paths.

Task 2 passed its specification review. Its final code-quality re-review was stopped
to conserve the originating Codex quota after all previously reported findings were
fixed; rerun that review before extending the implementation.

## Continue in this order

The original plan's Task 3 refers to `RunIdentity`, which is not introduced until
Task 5. Avoid either inventing a temporary identity type or building the report
twice.

1. Rerun the Task 2 code-quality review over `756e4a9..203e500`.
2. Implement a dependency-safe Task 3A: `LedgerSummary`, canonical ledger digest,
   deterministic fact block, and evaluator reconciliation. Turn the intentional
   replay failure green.
3. Implement Task 5's immutable run identity and closed stage machine.
4. Implement Task 6's atomic run store outside inspected roots.
5. Finish Task 3B's complete typed `ReportModel` against the real `RunIdentity`.
6. Implement Task 4 receipts, then Tasks 7–13 from the approved plan.

Keep the plan's test-driven loop and two review gates for every task: specification
review first, then code-quality review.

## Constraints discovered during preparation

### Task 5 — consent and run state

- Receipt issuance belongs behind the authenticated loopback `/approve` action.
- Preparation must not snapshot approved-root metadata before consent.
- Keep the short-lived consent store separate from Task 6's durable run store.
- Reject Pydantic bypasses including `model_construct`, `model_copy`, and legacy
  `construct`/`copy` paths where they could break invariants.
- Include checkpoint, failure, artefact, inventory deletion, and server-integration
  coverage; these were easy to miss in the first plan pass.

### Task 7 — specialist agents

- Specialists propose opaque, schema-bound claims; the deterministic engine remains
  the only component allowed to reconcile and write conclusions.
- The signed catalogue currently exposes `active`, `dormant`, and `parked`. Do not
  invent a `held` state or infer held capability IDs.
- Mint engine-owned evidence tokens; existing evidence references are not globally
  unique or provenance-bound enough for specialist output.
- Keep release-distance analysis disabled until a signed capability-family contract
  exists.
- Reconcile with deterministic two-fold agreement and enforce the recommendation cap
  at the set level, not independently per specialist.

### Task 10 — MCP v2

- Use the official Python SDK constraint `mcp>=2.1.1,<3`.
- Server API: `from mcp.server import MCPServer`; stdio is `MCPServer(...).run()`.
- In-process tests use `from mcp import Client` and
  `Client(server, raise_exceptions=True)` under pytest-anyio.
- In-memory client tests do not prove stdout framing; keep a real stdio smoke test.
- Use `MCPError` for machine-readable required-step failures.

## Safety and release truth

- Work only on the continuation branch in an isolated worktree/cloud checkout.
- Never include Dave's raw vault, full session export, secrets, or personal paths.
- Preserve read-only-before-consent and no-vault-mutation guarantees.
- A draft PR may remain red while Task 3's deliberately failing evaluation exists;
  do not present it as release-ready.
- Do not merge, sign, publish, serve, deploy, or release until Tasks 3–13 and the
  final candidate proof are complete and Dave explicitly approves publication.

## Copy-paste Cursor Cloud prompt

```text
Continue the Dex Lens deterministic diagnosis engine from branch
codex/lens-deterministic-diagnosis-engine-build. Do not restart or redesign it.

First read:
- docs/superpowers/plans/2026-08-27-dex-lens-deterministic-diagnosis-engine-cursor-handoff.md
- docs/superpowers/specs/2026-08-27-dex-lens-deterministic-diagnosis-engine-design.md
- docs/superpowers/plans/2026-08-27-dex-lens-deterministic-diagnosis-engine.md

Tasks 1 and 2 are implemented through checkpoint commit 203e500. Rerun the final
Task 2 code-quality review, then continue with the dependency-safe ordering in the
handoff. Use failing-first tests and separate specification and quality reviews for
each task. Keep all work on the feature branch. Do not merge, publish, release,
deploy, or alter the live installer. Preserve the sanitised replay and never add
Dave's raw vault/session data or personal paths to the repository.
```
