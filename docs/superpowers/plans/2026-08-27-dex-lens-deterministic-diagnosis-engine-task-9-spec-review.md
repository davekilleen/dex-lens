# Task 9 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped CLI adapter. Later default-engine wiring
does not change the command contract.

## Scope under review

`dex-lens diagnosis` as a shallow JSON adapter over an injected engine.
Consent issuance stays on the authenticated local `/approve` surface.
This review does not redesign Tasks 7, 8, 10 or 11.

## Contract the tests lock

1. `build_engine()` is the only construction hook. Tests monkeypatch it.
2. Commands are exactly `prepare`, `status`, `advance`, `submit`, `result`.
   An unknown word fails closed on stderr and writes nothing to stdout.
3. JSON on stdout is sorted compact canonical JSON. Human guidance and
   refusals go to stderr.
4. `prepare` records candidate folders and starts or reuses the existing
   local consent surface. It does not call `ScopeSnapshot.capture` and
   does not collect. `--wait` keeps that process alive until a receipt or
   persisted approval exists; tests must not pass `--wait`.
5. Collection happens only after authenticated `/approve` issues a receipt.
6. `result --format json` bytes equal `engine.result(...).dump_for_storage()`
   serialised the same way. `result --format markdown` prints only the
   canonical report markdown.
7. The CLI exposes no `--approve`, `--sign`, `--send`, `--install`,
   `--repair` or `--modify` flags.
8. `dex-lens diagnosis` is dispatched from the concierge CLI without
   opening a browser.

## Out of scope

MCP tools, skill wording, installer registration, and publication.
