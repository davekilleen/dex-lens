# Task 3B specification review

**Date:** 2026-08-27
**Verdict:** Pass against the implemented `ReportModel`. This review is
retrospective: Task 3B landed after Task 5's `RunIdentity` as the handoff
required.

## Scope under review

Typed `ReportModel` bound to `RunIdentity` and the exact comparison ledger.
Task 3A already owns `LedgerSummary`, the canonical fact block, and evaluator
reconciliation. Task 4 later attached receipts. This review does not redesign
those slices.

## Contract the tests lock

1. `ReportModel.from_result(...)` is the only construction path. Direct
   construction and unvalidated copy routes stay closed.
2. The supplied ledger digest must equal `canonical_ledger_digest(ledger)`.
3. Coverage counts come only from `LedgerSummary.from_ledger`. Markdown
   cannot invent its own totals.
4. `render_markdown` embeds the exact canonical fact block. The evaluator
   rejects omitted, altered, or contradictory coverage claims.
5. Capability-family `version_delta` / later-family fields stay absent until
   a signed family contract exists.

## Out of scope

Decision/share receipts (Task 4), the orchestrator, CLI/MCP adapters, and
publication.
