# Task 6 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Implement only after the new tests fail.

## Scope under review

Atomic diagnosis checkpoint persistence outside inspected roots.

- `DiagnosisRunStore` under `default_lens_app_storage(...) / "diagnosis-runs"`
- mode-`0600` temp file, flush, `fsync`, then `os.replace`
- refuse storage inside any approved root, symlinks, unknown run IDs and
  invalid digests
- `DiagnosisInputDrift` on input-identity mismatch
- `list_resumable()` returns only non-terminal valid checkpoints

## Out of scope

- specialist proposals, CLI/MCP adapters, and typed `ReportModel`
