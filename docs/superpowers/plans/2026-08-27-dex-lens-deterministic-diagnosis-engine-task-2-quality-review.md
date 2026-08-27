# Task 2 code-quality re-review

**Range:** `756e4a9..203e500`  
**Date:** 2026-08-27  
**Verdict:** Pass. No blocking defects. Continue to Task 3A.

This reruns the final Task 2 quality review that the originating session
stopped after fixing earlier findings. Specification review already passed.

## What was reviewed

- `src/capability_exchange/diagnosis/provenance.py`
- `src/capability_exchange/diagnosis/observations.py`
- `src/capability_exchange/adapters/claude_code/discovery.py`
- `src/capability_exchange/adapters/claude_code/snapshot.py`
- `src/capability_exchange/boundary/secret_markers.py`
- `tests/diagnosis/test_provenance.py`
- Focused discovery, snapshot, containment, inventory, and collection tests
  added in the same range

## Invariants that still hold

- Observations are unique by `(kind, identity, source_id)`. Same-name items
  from different approved sources stay distinct.
- `SourceProvenance` is frozen, extra-forbidden, and refuses absolute paths,
  home prefixes, traversal, controls, and secret-shaped locators.
- Working-copy observations are forced to `not-assessed` on construct, copy,
  and discovery paths.
- `copy()`, `model_copy()`, and `model_construct()` cannot bypass those
  validators on provenance, observations, fingerprints, or safe attributes.
- Snapshot relative locators that fail the same rejection rules become digest
  tokens instead of aborting collection or leaking a raw path.
- Live-state upgrades stay source-aware: unsourced live matches across more
  than one source remain `not-assessed` with an explicit ambiguity attribute.

## Residual notes, not blocking

- Validation-route overrides are repeated on each Task 2 model. That is
  intentional hardening against Pydantic bypasses, not accidental duplication
  to collapse.
- `relative_reference` still accepts a Windows drive letter without a slash
  (`C:foo`) and a `file:` URI. Snapshot collection already tokenises unsafe
  names, and the public-boundary cases named in the earlier hardening commits
  remain covered. Do not expand Task 2 now; if a later task treats
  `relative_reference` as a public locator, close those aliases then.

## Continue

Task 3A: `LedgerSummary`, canonical ledger digest, deterministic fact block,
and evaluator reconciliation. Do not introduce `RunIdentity` or a full
`ReportModel` until Task 5.
