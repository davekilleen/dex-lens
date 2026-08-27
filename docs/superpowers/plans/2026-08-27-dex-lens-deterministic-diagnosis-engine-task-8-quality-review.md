# Task 8 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Residual notes below are not blocking.

## What was reviewed

- `src/capability_exchange/diagnosis/orchestrator.py`
- `src/capability_exchange/diagnosis/__init__.py`
- `src/capability_exchange/reports/store.py`
- `tests/diagnosis/test_orchestrator.py`
- `tests/reports/test_report_store.py`
- Task 8 spec review

Specification review already passed.

## Invariants that hold

- Constructor dependencies are accepted and never constructed inside the
  engine. Public methods are only `prepare`, `status`, `advance`, `submit`,
  and `result`.
- `prepare` delegates to `LocalScopeConsentAuthority.prepare`. Tests prove it
  does not call the collector or `ScopeSnapshot.capture`.
- Stage movement uses `advance_to`. One call performs at most one stage.
- Collection runs only after an approved-scope receipt exists.
- Each stage calls exactly its lawful dependency. The engine never calls
  `LensReportStore.save(markdown)`.
- `save_result` renders canonical markdown from the typed result, writes
  ledger JSON and result JSON beside it, and verifies the three digests.
- Failed reconciliation raises before `saved` and leaves the previous
  checkpoint. `closed` refuses `advance` and `submit`.
- `submit` uses Task 7 `validate_proposal` and does not change the
  fingerprint digest.
- Catalogue availability is not extended with `held`. Unavailable
  recommendation IDs are parked/dormant identities on the catalogue slice.
- Release-distance stays disabled unless `family_contract_present` is true.
- Orchestrator imports do not reach adaptation, contribution, or share.
- Package export of the engine is lazy so adapters can import
  `capability_exchange.diagnosis` without a circular import through
  concierge/collection.
- Existing report-store, CLI, MCP, receipt, specialist, and report-model
  tests stay green. `build_engine()` remains an injectable raise-until-wired
  factory.

## Residual notes, not blocking

- The plan's two sequential `advance()` calls after a successful persist are
  not the same checkpoint. The required idempotence test rewinds to the
  pre-transition checkpoint, then advances again. Sequential calls after a
  successful persist progress one lawful stage.
- Artifact blobs are digest-addressed JSON under `diagnosis-runs/artifacts/`.
  They are not new InventoriedModels. Checkpoints bind them by digest, and
  `delete-diagnosis-run-state` already walks that directory.
- Default `build_engine()` still raises a clear missing-engine error. Wiring
  a process-wide default from real collector/catalogue/comparer deps is left
  to a later adapter slice so monkeypatch tests stay untouched.
- `VerifiedCatalogueSlice` is the Protocol return type. A production wrapper
  around `VerifiedCatalogueStore.load_last_verified` is not constructed
  inside the engine.

## Continue

Task 12 can replay the same engine through CLI and MCP. Do not merge,
publish, or change the installer or version `0.1.12`.
