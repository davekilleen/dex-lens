# Task 7 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Continue to Task 8.

## What was reviewed

- `src/capability_exchange/diagnosis/specialists.py`
- `tests/diagnosis/test_specialists.py`
- `src/capability_exchange/boundary/data_inventory.yaml`

Specification review already passed.

## Invariants that hold

- `SpecialistRole` is the closed six-role vocabulary. Invented role strings
  are refused by the enum.
- Proposals cite only engine-owned tokens present in `ProposalContext`.
  Foreign tokens and mismatched fingerprint digests raise
  `SpecialistProposalError` matching `"current fingerprint"`.
- `held_ids` means "not available to recommend." Signed catalogue
  availability remains `active` / `dormant` / `parked`; no `held` member
  was added.
- Matching proposals group by `(kind, catalogue_id, capability_id)` and
  coalesce with sorted evidence IDs. Conflicting dispositions become one
  `not-assessed` result with the exact disagreement sentence. No confidence
  field exists.
- The three-recommendation cap is enforced on the reconciled set, not per
  specialist.
- Release-distance claims of a usable disposition are refused until
  `family_contract_present` is true. Honest `not-assessed` claims pass.
- `copy()` is disabled. `model_copy` and `model_construct` re-validate
  through `_ValidatedInventoried`.
- `specialists.py` does not import adaptation, contribution, or share.
- New inventoried fields are ephemeral (`storage: none`).

## Residual notes, not blocking

- Token minting is available for Task 8. This slice does not persist
  proposals or write ledger conclusions.
- Role-specific observation filtering stays with the orchestrator. The
  shard currently carries the engine's current identity set.
- Collapsed provenance is an explicit context set, not a new observation
  state.

## Continue

Task 8: implement the deep deterministic engine interface that validates
proposals and writes conclusions.
