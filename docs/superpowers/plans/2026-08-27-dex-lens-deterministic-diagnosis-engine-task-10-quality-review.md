# Task 10 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Continue to later adapter/engine tasks.

## What was reviewed

- `src/capability_exchange/diagnosis/mcp_server.py`
- `tests/diagnosis/test_mcp_server.py`
- `tests/test_packaging.py`
- `pyproject.toml`

## Invariants that hold

- The adapter is translation only: tools call an injected `DiagnosisEngine` and return `dump_for_storage()`.
- `build_engine()` is a monkeypatchable hook. This slice does not construct Task 8's orchestrator.
- The advertised tool set is exactly the five read-only diagnosis tools. Names contain none of `write`, `delete`, `install`, `repair`, `share`, or `send`.
- Unknown tool-argument fields are refused (`extra="forbid"` on locked argument models).
- Secret canaries and absolute paths are refused from retained MCP payloads and from stdio stdout.
- `advance_diagnosis` before a consent receipt raises `MCPError` with `data.required_step == "approve_scope"` and does not collect.
- Closed-result bytes match the injected engine. CLI equality is documented as waiting for Task 9.
- `dex-lens-mcp` is a console script. Existing wheel data-file gates still pass. Package version remains `0.1.12`.

## SDK notes

- Installed API matches the handoff: `MCPServer`, `Client`, `MCPError`, `MCPServer.run(transport="stdio")`.
- In-process `Client(server)` does not prove newline JSON-RPC framing; a real stdio subprocess test does.
- The official argument models ignore extras; the adapter locks each tool model to `extra="forbid"` after registration.

## Out of scope still

Task 8 orchestrator, Task 7 specialists, Task 4 receipts, Task 9 CLI, Task 11 skill, installer registration.
