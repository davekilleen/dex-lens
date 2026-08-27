# Task 10 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Implement only after the new tests fail.

## Scope under review

Thin read-only MCP v2 stdio adapter over an injected diagnosis engine.

- official SDK constraint `mcp>=2.1.1,<3`
- server construction `from mcp.server import MCPServer`; stdio is `MCPServer(...).run()`
- in-process tests `from mcp import Client` and `Client(server, raise_exceptions=True)` under the installed anyio pytest plugin
- real stdio smoke test (in-memory client tests do not prove stdout framing)
- `MCPError` for machine-readable required-step failures
- injectable `build_engine()` / Protocol-shaped fake engine (Task 8 orchestrator is absent)

## Inspected SDK APIs (mcp 2.1.1)

The installed package matches the handoff:

- `mcp.server.MCPServer`
- `mcp.Client` (also `mcp.client.client.Client`)
- `mcp.MCPError` / `mcp.shared.exceptions.MCPError`
- `MCPServer.run(transport="stdio")` → `anyio.run(self.run_stdio_async)`
- `Client(server)` accepts an in-process `MCPServer`
- `Client(StdioServerParameters(...))` launches a real stdio subprocess
- tool registration is `@server.tool()` / `server.add_tool()`
- `MCPError` raised from a tool becomes a JSON-RPC protocol error (not `CallToolResult(is_error=True)`)

## Contract the tests lock

1. The advertised tool set is exactly `EXPECTED_TOOLS`. No other tools.
2. No tool name contains `write`, `delete`, `install`, `repair`, `share`, or `send`.
3. Unknown Pydantic fields on tool arguments are refused.
4. Secret canaries and absolute paths are refused from retained MCP payloads and stdout.
5. `advance_diagnosis` before a consent receipt returns structured `MCPError` and does not collect.
6. For one closed synthetic run, sorted compact JSON bytes of `engine.result(run_id).dump_for_storage()` equal `get_diagnosis_result`. CLI equality waits for Task 9.
7. `dex-lens-mcp` is a declared console script. Existing wheel data-file gates stay intact.

## Out of scope

- Task 8 `DeterministicDiagnosisEngine` orchestrator
- Task 7 specialist validation / reconciler
- Task 4 receipts
- Task 9 CLI adapter
- Task 11 skill rewrite
- installer registration, version bump, or public release (package stays 0.1.12)
