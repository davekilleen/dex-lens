# Task 12 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice.

## What was reviewed

- `src/capability_exchange/evaluation/replay.py`
- `tests/evals/test_real_session_replay.py`
- `tests/evals/test_adapter_conformance.py`
- `tests/evals/test_interrupted_run.py`
- `tests/adapters/claude_code/test_surface_read_only.py`
- Task 12 spec review

Specification review already passed.

## Invariants that hold

- `run_direct`, `run_cli`, and `run_mcp` share one `ReplayBundle`: the same
  fingerprint, catalogue slice, ledger, proposal tuple, fixed clock, and
  fixed run id. Each helper builds an equivalent injected engine from that
  bundle. Transports differ; engine inputs do not.
- Canonical bytes are sorted compact JSON of
  `DiagnosisResult.dump_for_storage()`. Direct, CLI (`diagnosis_main` plus
  monkeypatched `build_engine`), and in-process MCP `Client` match for
  `forward`, `reverse`, and `rotated` source order.
- Fake Claude-style and Codex-style callers list MCP tools in different
  orders and still obtain the same bytes.
- Every non-terminal stage can stop, rebuild the engine over the same run
  store and consent store, resume, and match an uninterrupted run.
- A changed stored scope digest refuses resume as `DiagnosisInputDrift`.
- Count, catalogue-hash, evidence-reference, decision-state, share-state,
  and source-class mutations fail before `SAVED` and leave the previous
  checkpoint in place.
- `INVENTED_SESSION_CANARY_NEVER_RETAIN` is absent from fingerprints,
  checkpoints, reports, and MCP result bytes.
- Diagnosis package imports, plus `evaluation.replay`, do not reach
  adaptation, contribution, share, subprocess, or generic network clients.
- The false-coverage rejection (`93 capabilities are already covered`)
  stays. Catalogue availability is not extended with `held`.

## Residual notes, not blocking

- In-process MCP is the Task 12 equality proof. Task 10 already has a real
  stdio smoke against a fake engine; this slice does not replay the
  sanitised session over stdio again.
- MCP's wire proposal shape remains Task 10's translation-only `{claims}`.
  If a replay bundle carries Task 7 proposals, `run_mcp` submits them on
  the injected engine instance after `catalogue-verified`. The golden
  fixture uses an empty proposal tuple.
- Save-time integrity compares the reconstructed result to the original
  bundle so a mutated ledger or fingerprint cannot be persisted as
  `SAVED`. Decision and share mutations go through `ReportModel.from_result`
  because the engine reconstructs the report and does not store a second
  copy of those fields.
- Catalogue verification's existing `urllib.request` path stays outside
  `capability_exchange.diagnosis`. The import walk is AST over diagnosis
  and replay modules, not a transitive walk into catalogue fetch.

## Continue

Task 13 records candidate truth. Do not merge, publish, or change the
installer or version `0.1.12`.
