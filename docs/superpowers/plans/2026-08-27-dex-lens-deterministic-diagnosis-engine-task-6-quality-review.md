# Task 6 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Continue to Task 3B.

## What was reviewed

- `src/capability_exchange/diagnosis/run_store.py`
- `src/capability_exchange/catalogue/subscription.py`
- `tests/diagnosis/test_run_store.py`

## Invariants that hold

- The store refuses a directory inside any approved root.
- Checkpoints write through a mode-`0600` sibling temporary file, flush,
  `fsync`, and `os.replace`. A failed replace leaves the previous checkpoint.
- `load` refuses unknown run IDs, non-canonical payloads, and input-identity
  drift.
- `list_resumable` returns only valid non-closed checkpoints, oldest first.

## Continue

Task 3B: complete typed `ReportModel` against the real `RunIdentity`.
