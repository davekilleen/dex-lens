# Task 8 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Implement only after the new tests fail.

## Scope under review

Deep `DeterministicDiagnosisEngine` orchestrator and `LensReportStore.save_result`.
CLI and MCP stay thin injectable adapters. Tasks 4/7/9/10/11 are not redesigned.

## Contract the tests lock

1. Constructor dependencies are accepted, never constructed inside the engine:
   `run_store`, `consent_authority`, `collector`, `catalogue_loader`,
   `comparer`, `report_store`, `clock`.
2. Public methods are only `prepare`, `status`, `advance`, `submit`, `result`.
3. `prepare` reads nothing. It delegates candidate-scope display to
   `LocalScopeConsentAuthority.prepare`. It does not call the collector or
   `ScopeSnapshot.capture`. It returns `DiagnosisRunView` at `created` with
   the next action to approve the exact scope.
4. `advance` before a local approved-scope receipt raises
   `DiagnosisStateError` matching `"approve the exact scope"`.
5. `result` before `closed` raises `DiagnosisStateError` matching `"not closed"`.
6. `advance` is idempotent for the same persisted checkpoint: replaying the
   same pre-transition checkpoint yields the same public view. Sequential
   calls after a successful persist progress one lawful stage; they are not
   the same checkpoint. The engine uses `advance_to` and does not invent a
   second stage machine.
7. Each later call loads the checkpoint, validates digest / input identity,
   requires the exact consent receipt where applicable, performs at most one
   stage, stores artifacts by digest, and returns a non-secret
   `DiagnosisRunView`.
8. Each stage calls exactly its lawful dependency:
   collector at `captured`, catalogue loader at `catalogue-verified`,
   comparer at `compared`, `report_store.save_result` at `saved`.
   Collection cannot run before an approved-scope receipt exists.
9. Failed reconciliation never reaches `saved`. The previous checkpoint stays.
10. `closed` exposes no mutation port: `advance` and `submit` refuse.
11. `submit` validates through Task 7 (`validate_proposal`) and cannot alter
    evidence (fingerprint digest stays).
12. `save_result` consumes a typed result, renders canonical markdown
    internally, writes ledger JSON and result JSON beside the report, and
    verifies the three digests before returning. The engine never calls
    `save(markdown)`. Legacy `save(markdown)` remains for read/list only.
13. Catalogue availability stays `active` / `dormant` / `parked`. Unavailable
    recommendation IDs are parked/dormant identities, not a `held` member.
14. Release-distance stays disabled unless the loaded catalogue slice reports
    a signed family contract.
15. Diagnosis orchestrator does not import adaptation, contribution, or share.
16. Pydantic bypasses stay closed on existing inventoried models. New
    persisted InventoriedModel fields, if any, use `delete-diagnosis-run-state`.
17. Engine `prepare` accepts Path-or-str roots so CLI (`tuple[Path, ...]`) and
    MCP (`tuple[str, ...]`) can call it without a breaking adapter rewrite.
18. `build_engine()` stays injectable. Default construction may raise a clear
    error if dependencies are missing so monkeypatch tests stay green.

## Protocol mapping (do not invent a second stack)

- `FingerprintCollector.collect(receipt)` wraps existing collection
  (`CollectionController` / `discover_fingerprint`). It is a constructor-
  injected Protocol, not a new collector implementation.
- `VerifiedCatalogueLoader.load(...)` wraps `VerifiedCatalogueStore` and
  returns a slice with version, digest, identities, parked/dormant
  unavailable IDs, and `family_contract_present`.
- `ComparisonBuilder.compare(...)` wraps `ComparisonLedger` construction
  (`ComparisonLedger.for_catalogue` / existing disposition types).

## Out of scope

- live installer, package version `0.1.12`, SKILL.md, publish/merge
- redesign of receipts, specialists, CLI, MCP, or the atomic run store
- a second collector stack or a `held` catalogue availability member
