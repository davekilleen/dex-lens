# Task 7 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Implement only after the new tests fail.

## Scope under review

Bounded specialist proposal vocabulary, validation, and deterministic
disagreement handling. Specialists propose opaque, schema-bound claims.
Only later Task 8 reconciles those claims into engine conclusions.

- closed `SpecialistRole` and `ProposalKind` vocabularies
- `SpecialistShard`, `SpecialistProposal`, `ProposalContext`,
  `ValidatedProposal`
- `validate_proposal` and set-level `reconcile_proposals`
- engine-owned evidence tokens
- recommendation availability without inventing catalogue `held`
- release-distance disabled until a signed capability-family contract exists
- bypass-safe frozen models

## Contract the tests lock

1. Foreign evidence IDs raise `SpecialistProposalError` matching
   `"current fingerprint"`.
2. Recommending an ID in `held_ids` / `unavailable_ids` raises
   `SpecialistProposalError` matching `"not available"`. Those IDs mean
   "not available to recommend"; they are not a new catalogue availability
   member. Signed availability remains `active` / `dormant` / `parked`.
3. Matching proposals group by `(kind, catalogue_id, capability_id)` and
   coalesce with sorted evidence IDs. Conflicting dispositions become one
   `not-assessed` result with the exact reason
   `Specialist proposals disagreed; the comparison remains Unknown.`
4. No confidence field exists and no score breaks a disagreement.
5. `copy()` is disabled; `model_copy` and `model_construct` re-validate.
6. Invented role strings are refused.
7. Release-distance claims of usable family distance are refused when no
   signed capability-family contract is present.
8. The recommendation cap is enforced on the reconciled set, not
   independently per specialist.
9. Diagnosis specialists do not import adaptation, contribution, or share.

## Out of scope until later tasks

- orchestrator, CLI, MCP
- receipts, report wiring, SKILL.md, installer, version
- writing conclusions into the comparison ledger (Task 8)
- signed capability-family contract (separate family plan)
