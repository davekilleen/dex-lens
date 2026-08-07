# Dex Capability Exchange (working name "Outward Dex")

A standalone, local-first product in the Dex family that privately diagnoses a person's
**existing** personal AI system at the user-job level, helps them selectively adapt
evidence-backed Dex capabilities **without migrating to Dex**, and lets them explicitly
contribute chosen, previewable Capability Cards back to Dex.

## The standing contract

These commitments are binding on all implementation (from the Wayfinder planning record,
davekilleen/Dex #347):

- **The person keeps and improves their existing system.** Dex installation or migration
  is never required.
- **Diagnosis is private and read-only.** It gathers evidence and produces a Capability Map
  without changing the person's system — enforced at the operating-system capability level,
  not by convention. The diagnosis side never holds a write capability.
- **Every finding exposes three separate axes** — Capability State, Evidence Level, and
  Safety Boundary — never collapsed into an aggregate score, maturity rank, or
  Dex-resemblance percentage.
- **Nothing is shared by default.** Sharing back is optional per use case; the person
  inspects, edits, redacts, and approves each Capability Card separately. Contribution is
  never the price of diagnosis.
- **Adaptation is separate** from diagnosis: selective, previewed, reversible, and
  explicitly approved — one bounded change at a time, with proven recovery or honest refusal.
- **Local-first, not local-only.** Diagnosis and private recommendations work offline,
  without an account.

Out of scope, permanently: requiring migration to Dex or scoring systems by resemblance to
Dex; uploading raw system contents, prompts, histories, or personal data as the price of
diagnosis; automatically adopting contributed capabilities into Dex Core.

## Status

**Milestone 1: containment core under construction.** Current work: the versioned Host
Adapter contract, the contained Claude Code deep adapter (evidence collector, not agent),
the immutable-snapshot read path, the G2 field inventory and typed serialization boundary,
the R2 evidence-state vocabulary, and the hostile fixture catalog. See
`docs/handoff/HANDOFF.md` for the full build plan and `docs/handoff/sources/gates.md` for
the testable acceptance gates — the gates are the spec.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Read `CONTRIBUTING.md` before writing code: test-first, fail closed, and use the binding
domain vocabulary exactly.
