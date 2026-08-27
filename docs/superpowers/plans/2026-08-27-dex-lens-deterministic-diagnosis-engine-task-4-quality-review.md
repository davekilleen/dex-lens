# Task 4 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Decision and share completion claims
are receipt-backed.

## What was reviewed

- `src/capability_exchange/diagnosis/receipts.py`
- `src/capability_exchange/diagnosis/report.py`
- `src/capability_exchange/boundary/data_inventory.yaml`
- `tests/diagnosis/test_receipts.py`
- `tests/diagnosis/test_report_model.py`

Specification review already passed after the two fixes below.

## Invariants that hold

- Receipt models are frozen, `extra="forbid"`, and re-validate on
  `model_copy` / `model_construct`. `copy()` is disabled.
- Chosen and completed decisions are unrepresentable without a local
  `DecisionReceipt` whose catalogue ID and state match.
- `ShareReceipt.preview` cannot be sent. `sent` requires destination class
  plus response digest. `was_sent` is derived, not a writable field.
- `ReportModel` stays factory-only through `from_result`. Direct construction
  and `model_construct` remain refused. The exact ledger digest check is
  unchanged.
- `render_markdown` still embeds `canonical_fact_block` first under Coverage
  and limits. Existing ledger-fact tests stay green.
- Decision and share wording have no input field. “taken” and “shared” are
  rendered only from confirmed receipts. Preview wording never uses `shared`.
- The close always emits the six design fields, including honest empty
  answers and a separate future-watch line.
- New inventoried fields are `storage: none` / `deletion: not-stored`.
  Receipts raise `EphemeralByDefaultError` on `dump_for_storage()`.
- Diagnosis receipt and report modules do not import adaptation,
  contribution, or share packages.
- `scripts/check_inventory.py` is green. Ruff is green on the touched files.

## Findings found and fixed

1. **Inventory namespace collision.** A second `_ValidatedInventoried` class
   would have shared inventory keys with the run mixin. Renamed to
   `_ClosedReceiptModel`.
2. **Contradictory share receipt.** `ShareReceipt(state=not-offered)` is now
   refused. `not-offered` remains the report default when no receipt exists.
3. **Sent close wording.** The renderer now checks destination class and
   response digest explicitly before saying `shared`, matching `was_sent`.

## Residual notes, not blocking

- `_ClosedReceiptModel` duplicates the run mixin under a unique name because
  the inventory keys models by bare class name. A later shared helper would
  need a single public name.
- `from_result` still assigns reciprocal and reliability findings to empty
  tuples. Callers cannot yet pass those axes. Pre-existing.
- Report location is always “not been saved yet”. Correct until a save path
  exists.

## Continue

Keep Task 4 on `cursor/task-4-receipts-dc36`. Do not merge to the build
branch. Do not change version 0.1.12 or the installer.
