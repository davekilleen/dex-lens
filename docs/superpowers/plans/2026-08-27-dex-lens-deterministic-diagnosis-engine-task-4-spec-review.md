# Task 4 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice after the inventory-name collision and
`not-offered` receipt hole were closed.

## Scope under review

Handoff Task 4: bind Lens decisions and sharing to typed receipts so a report
cannot claim “taken” or “shared” from free-form prose.

- closed `DecisionState` and `ShareState`
- `DecisionReceipt`, `RecommendationDecision`, and `ShareReceipt`
- `ReportModel` fields `decisions`, `share_state`, and `share_receipt`
- markdown derived only from those objects
- no specialists, orchestrator, CLI, MCP, installer, or version change

## Contract the tests lock

1. `ShareReceipt.preview(...)` is `previewed` and `was_sent` is false.
2. `RecommendationDecision` with `chosen` or `completed` refuses `receipt=None`
   with `decision receipt` in the error.
3. `offered` may exist without a receipt. Chosen/completed need a matching
   local receipt.
4. `sent` additionally requires a bounded destination class and a response
   receipt digest. Preview cannot carry a response digest.
5. Receipts are frozen, extra-forbid, timezone-aware UTC, and closed against
   `copy()` / validating `model_construct`.
6. `ReportModel.from_result` still requires the exact comparison ledger digest
   and remains factory-only.
7. `render_markdown` still inserts `canonical_fact_block` first under Coverage
   and limits. “What you decided” and share/close wording come only from
   receipt objects. There is no pre-rendered prose field.
8. The word `taken` appears only for receipt-backed chosen/completed
   decisions. The word `shared` appears in the close only for a sent receipt
   that names destination class, disclosure digest, and response digest.
9. The close always includes strengths, reciprocal value, first move, report
   location, how to return to the run, and separate sharing / future-watch
   choices. Empty answers are explicit.

## Intentional design choices

- The design sketch typed `decisions` as `tuple[DecisionReceipt, ...]`. That
  cannot represent an offered recommendation that was only shown. The
  implemented type is `tuple[RecommendationDecision, ...]`, where
  `RecommendationDecision.receipt` is required for chosen/completed. That is
  the clean typed design.
- `ReportModel` still has no `version_delta`, `recommendations`, or
  `later_families`. Those belong to a later slice. They were not invented.
- Catalogue availability remains active/dormant/parked. This slice does not
  add a `held` state.
- Destination class is a diagnosis-local closed vocabulary
  (`contribution-intake`). Diagnosis does not import adaptation, contribution,
  or share packages.
- Report location is the honest empty answer “not been saved yet”. No save
  path is persisted in this slice.

## Findings found and fixed during review

1. Duplicating run.py’s `_ValidatedInventoried` name collided in
   `scripts/check_inventory.py`, which keys models by bare class name. The
   receipts mixin was renamed to `_ClosedReceiptModel`.
2. A `ShareReceipt` could be constructed with `ShareState.NOT_OFFERED`, which
   is a report default, not a receipt. That state is now refused on the
   receipt.

## Residual notes, not blocking

- `ShareReceipt.preview` accepts a placeholder run ID so the plan-required
  two-argument factory stays valid. Attaching a preview to a `ReportModel`
  still requires the real run ID.
- Future-watch is honest static text, not a receipt type. A later slice can
  add a watch receipt if one is specified.
- Reciprocal and reliability finding tuples remain empty in `from_result`.
  That predates this slice.

## Out of scope until later tasks

- durable save path and `reports check` / `reports save`
- specialists, orchestrator, CLI, MCP
- family and version-distance report fields
