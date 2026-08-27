# Task 3A code-quality review

**Date:** 2026-08-27  
**Verdict:** Pass for the scoped slice. Continue to Task 5.

## What was reviewed

- `src/capability_exchange/diagnosis/report.py`
- `src/capability_exchange/diagnosis/comparison.py`
- `src/capability_exchange/evaluation/diagnosis.py`
- `src/capability_exchange/boundary/data_inventory.yaml`
- `tests/diagnosis/test_report_model.py`
- `tests/evals/real_session_fixture.py`
- `tests/evals/test_legacy_system_diagnosis.py`

Specification review already passed.

## Invariants that hold

- `LedgerSummary` exists only through `from_ledger()`. Direct construction,
  `copy()`, `model_copy()` of counts, and `model_construct()` are refused.
- Coverage numbers are calculated from ledger entries. They are not a second
  source of truth that a report can invent.
- `canonical_ledger_digest` is a stable SHA-256 of the ledger payload. A
  disposition change changes the digest.
- `canonical_fact_block` is the digest line plus the exact catalogue
  accounting and disposition lines.
- `evaluate_diagnosis` fails a report that omits, alters, or contradicts
  that block. The sanitised replay now fails the contradictory 93-coverage
  claim on ledger reconciliation, not on a forbidden-phrase list.
- Inventory fields for the four summary counts are storage none / sharing
  never.

## Residual notes, not blocking

- `LedgerSummary.model_copy` still allows a no-op copy. That is the same
  pattern as Task 2 models: only count fields are refused.
- Disposition order in the fact block follows the live `Disposition` enum,
  not the example string in the original plan.
- `tests/evals/test_legacy_system_diagnosis.py` still needs a real-machine
  filesystem for snapshot collection. This Cloud VM marks the invented
  fixture trees as mount-point crossings and admits zero files. Do not
  weaken those guards to make the test green here. The fact-block insertion
  is already in the complete two-way report.

## Continue

Task 5: immutable run identity and closed stage machine. Do not start the
full typed `ReportModel` until that identity exists.
