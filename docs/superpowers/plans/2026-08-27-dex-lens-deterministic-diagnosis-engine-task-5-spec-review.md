# Task 5 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Implement only after the new tests fail.

## Scope under review

Handoff Task 5, using the constraints discovered during preparation:

- immutable `RunIdentity` and closed `DiagnosisStage` machine
- `ApprovedScopeReceipt` issued only after local consent
- `DiagnosisInput` identity digest bound to scope, catalogue, fingerprint,
  engine and assessment time
- `DiagnosisCheckpoint` with previous digest, input identity, artefact
  digests and next action
- `LocalScopeConsentAuthority` with a short-lived consent store
- no Task 6 durable run store
- no complete `ReportModel`

## Contract the tests lock

1. `DiagnosisStage` members are exactly the ten closed stages in order.
2. `advance_to` accepts only the next lawful stage; repeating the current
   stage is idempotent; skips and backwards moves raise
   `DiagnosisStateError`.
3. `DiagnosisInput.identity_digest` changes when the approved scope changes
   and is stable for the same input.
4. `prepare` records only a run ID and opaque candidate locators. It does
   not snapshot approved-root metadata or issue a receipt.
5. Only `approve_from_local_session` can issue `ApprovedScopeReceipt`.
   `receipt_for` is read-only.
6. Receipt issuance on the HTTP surface happens behind the authenticated
   loopback `/approve` action.
7. Naive timestamps, `copy()`, validating `model_copy` bypasses, and
   `model_construct` cannot forge a receipt or checkpoint.

## Out of scope until later tasks

- atomic disk persistence of checkpoints (Task 6)
- typed `ReportModel` (Task 3B)
- decision and share receipts (Task 4)
