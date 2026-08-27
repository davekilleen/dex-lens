# Task 5 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Continue to Task 6.

## What was reviewed

- `src/capability_exchange/diagnosis/run.py`
- `src/capability_exchange/concierge/consent.py`
- `src/capability_exchange/concierge/server.py`
- `src/capability_exchange/boundary/data_inventory.yaml`
- `src/capability_exchange/boundary/deletion.py`
- `tests/diagnosis/test_run.py`
- `tests/concierge/test_diagnosis_consent.py`

Specification review already passed.

## Invariants that hold

- `DiagnosisStage` is the closed ten-stage machine. `advance_to` is
  idempotent for the current stage and refuses skips or backwards moves.
- `DiagnosisInput.identity_digest` is a SHA-256 of stored input fields and
  changes when the approved scope changes.
- `LocalScopeConsentAuthority.prepare` records only a run ID and opaque
  candidate locators. It does not call `ScopeSnapshot.capture`.
- Receipts are issued only by `approve_from_local_session`. CLI/MCP can call
  `receipt_for` but have no approval method.
- The authenticated loopback `/approve` action issues that receipt when a
  diagnosis run is attached to the session.
- Naive timestamps, `copy()`, and `model_construct` keep validators active.
- Inventory fields for run state declare `delete-diagnosis-run-state`.

## Residual notes, not blocking

- The short-lived consent store is in-memory. Task 6 owns durable checkpoint
  files under `diagnosis-runs/`.
- `previous_decisions` and raw `catalogue_bytes` wait for later tasks. The
  input identity already binds catalogue hash, fingerprint hash, engine
  version and scope receipt.
- The existing Linux contained-journey test still depends on a real
  filesystem that this Cloud VM may treat as a mount-point crossing. Do not
  weaken that guard.

## Continue

Task 6: persist checkpoints atomically outside inspected roots.
