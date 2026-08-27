# Task 3A specification review

**Date:** 2026-08-27  
**Verdict:** Pass for the scoped slice. Implement only after the new tests fail.

## Scope under review

Handoff Task 3A, not the original plan's full Task 3:

- `LedgerSummary` derived only from a `ComparisonLedger`
- canonical ledger digest
- deterministic fact block
- evaluator reconciliation that turns the intentional replay failure green
- no `RunIdentity`
- no complete typed `ReportModel`

## Contract the tests lock

1. `LedgerSummary.from_ledger` reproduces the sanitised replay counts:
   115 total, 35 assessed, 80 unknown, and the seven closed dispositions.
2. Independent construction of those numbers is refused. The summary cannot
   become a second source of truth.
3. `canonical_ledger_digest` is `sha256:` plus 64 lowercase hex characters,
   stable for the same ledger, and different after a disposition change.
4. `canonical_fact_block` is the digest line plus the exact catalogue
   accounting and disposition lines from the approved plan.
5. `evaluate_diagnosis` reports `ledger-derived facts` when the block is
   missing, altered, or contradicted by another coverage-number sentence.
6. The existing replay still uses `without_literal_blacklist()`, so the
   failure cannot be a forbidden-phrase check.

## Out of scope until later tasks

- `ReportModel.from_result(..., run_identity=...)`
- receipts, stages, MCP, specialists, and installer changes
