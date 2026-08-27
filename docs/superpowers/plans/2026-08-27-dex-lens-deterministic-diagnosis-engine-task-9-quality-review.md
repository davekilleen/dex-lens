# Task 9 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped CLI adapter.

## What was reviewed

- `src/capability_exchange/diagnosis/cli.py`
- `tests/diagnosis/test_cli.py`
- `src/capability_exchange/concierge/cli.py`
- `src/capability_exchange/concierge/server.py`
- later wiring in `src/capability_exchange/diagnosis/defaults.py`

Specification review already passed.

## Invariants that hold

- The module is translation only: parse argv, call the injected engine,
  print canonical JSON or markdown.
- `build_engine()` now returns `build_default_engine()`. Tests still
  monkeypatch the hook, so the process-default ports are not exercised
  by the Task 9 suite.
- `start_or_reuse_consent_surface` attaches `consent_authority` and
  `run_store` to the existing session. It does not snapshot or collect.
- `/approve` is the only issuer of `ApprovedScopeReceipt`. The CLI cannot
  mint one.
- Persisted `PersistedScopeApproval` lets a later process resume after
  `prepare --wait` or after the consent surface wrote the sidecar.
- Ruff is clean. Inventory covers the new sidecar fields with
  `delete-diagnosis-run-state`.

## Residual notes, not blocking

- Multi-root `prepare` now generates default vault-authored descriptors
  when the caller did not name sources. Named descriptors still win.
- The default comparer starts every catalogue identity as not-assessed
  and applies only reconciled specialist proposals. That belongs to the
  process engine, not to this CLI slice.

## Continue

Task 13 candidate proof and GitHub CI remain the publication gate.
Do not merge, sign, or change the live installer from this review.
