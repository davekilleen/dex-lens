# Task 12 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Implement only after the new tests fail.

## Scope under review

Golden replay of the sanitised real-session fixture through the same
injected engine over three transports: direct `DeterministicDiagnosisEngine`,
`diagnosis_main`, and in-process MCP `Client`. Prove order invariance,
interruption/resume, stale scope refusal, hostile factual mutations, and
that diagnosis imports never reach adaptation, contribution, sharing,
subprocess execution, or a generic network client.

Do not publish, merge, change the installer, or bump version `0.1.12`.
Do not invent a `held` catalogue state. Do not weaken
`test_real_session_replay.py`'s false-coverage rejection.

## Contract the tests lock

1. `run_direct`, `run_cli`, and `run_mcp` accept the same sanitised
   `ReplayBundle` (fingerprint, catalogue slice, ledger, proposal tuple,
   fixed clock, fixed run id). They vary transport only. They do not
   construct different collector, catalogue, comparer, clock, or proposal
   inputs.
2. Each helper returns canonical result bytes: sorted compact JSON of
   `DiagnosisResult.dump_for_storage()`.
3. `run_cli` drives `diagnosis_main` against the same injected
   `build_engine` factory. `run_mcp` drives in-process
   `Client(server, raise_exceptions=True)` against `build_mcp_server`
   wrapping the same engine instance. Neither helper reimplements
   diagnosis.
4. For every ordering in `forward`, `reverse`, and `rotated`, the three
   transports produce one identical byte string.
5. Fake Claude-style and Codex-style callers that discover MCP tools in
   different orders still obtain the same canonical result bytes.
6. For every non-terminal stage, stop after the checkpoint, rebuild the
   engine over the same run store (and consent store), resume, and match
   an uninterrupted run's bytes.
7. Changing one stored scope digest refuses resume as stale
   (`DiagnosisInputDrift` / "no longer matches").
8. Mutating one count, catalogue hash, evidence reference, decision
   state, share state, or source class fails before `SAVED` and leaves
   the previous checkpoint intact.
9. `INVENTED_SESSION_CANARY_NEVER_RETAIN` is absent from fingerprints,
   checkpoints, reports, and MCP messages.
10. Imports beneath `capability_exchange.diagnosis` (and
    `capability_exchange.evaluation.replay` if it imports diagnosis)
    must not reach `capability_exchange.adaptation`,
    `capability_exchange.contribution`, `capability_exchange.share`,
    subprocess execution helpers, or generic network clients
    (`httpx` / `requests` / `urllib.request`).
11. Existing `test_report_cannot_claim_93_covered_when_80_are_not_assessed`
    stays green.

## Protocol mapping (do not invent a second stack)

- `FingerprintCollector.collect(receipt) -> EvidenceFingerprint`
- `VerifiedCatalogueLoader.load(...) -> VerifiedCatalogueSlice`
- `ComparisonBuilder.compare(...) -> ComparisonLedger`
- Consent: `LocalScopeConsentAuthority.approve_from_local_session`
- Prepare: `PrepareDiagnosisRequest.from_roots(...)`
- Result: `DiagnosisResult.dump_for_storage()` plus
  `canonical_result_bytes` for MCP equality

## Out of scope

- live installer, package version `0.1.12`, publish/merge
- a second stdio MCP smoke (Task 10 already has one)
- inventing `held` catalogue availability
- changing CLI, MCP, or orchestrator contracts except via injection
- weakening contained-journey / mount-point / macOS installer guards
