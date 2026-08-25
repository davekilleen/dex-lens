# Contributing

Three rules govern all work in this repository. They come from the handoff pack
(`docs/handoff/HANDOFF.md`) and the testable gates (`docs/handoff/sources/gates.md`, the
source of truth for acceptance).

## 1. Test-first: the gates are the spec

Write the fixture and the failing test **before** the feature. **A feature without its
hostile fixture is unfinished.** A milestone is done when its listed gate criteria pass in
CI, not when its features demo. Any hostile-fixture failure anywhere re-opens the
corresponding gate.

Prefer structural (schema-level) enforcement over checked behavior: make forbidden states
unrepresentable — only inventoried fields serializable (G2), no aggregate-score field in
any schema, allowlists as data — and back each with property tests (hypothesis) and
model-based state-machine tests.

## 2. Fail closed, everywhere

When a precondition cannot be verified, behave as if the gate failed — no automation, no
egress, no sharing, no continuation — and say so honestly rather than degrade silently.
Missing or unknown state maps to the most restrictive interpretation (`not assessed`,
`Inspection`, high-impact, untrusted, withdrawn). Never report success you cannot prove.

The diagnosis side never holds a write capability: no module on the diagnosis path may
expose a mutating entry point, ever. Read-only is enforced at the OS capability level, not
by convention.

## 3. Vocabulary is binding

Use the domain vocabulary in HANDOFF.md **Section 1.5** exactly — Capability, Foundation
Capability, Job Map, Diagnosis, Capability Map, Evidence Level, Host Adapter, Deep Adapter,
Living System, Capability Catalog, Adaptation, Capability Card, Contribution Preview,
Contribution, Core Candidate. The table's "Avoid" terms (e.g. "primitive", "scorecard",
"universal scanner", "migration", "telemetry event") must not appear in code, UI, or docs.

## 4. The two installers are one artifact

There are two install scripts: `install.sh` (run from a clone) and the signed release
installer rendered by `scripts/render_release_installer.py` (served at the address every
README, both web pages and the product hand to a person). Almost nobody runs the first;
everybody runs the second.

Any behaviour a person meets — argument handling, `--dry-run`, `--help`, the `PATH`
warning, the line printed to paste, the summary of what changed, the anonymous note — must
be present in **both** scripts or in neither. A fix that lands in only one of them is a fix
the running copy does not have; both worst defects a red-team pass found here were exactly
that. `tests/release/test_installer_parity.py` executes both and fails when they diverge;
it is the enforcement, not a note, so do not weaken it to make one side pass.

Fixing installer code is not the same as fixing the install. The served installer is pinned
to a released version, so work that lands here reaches nobody until a release is cut that
re-renders it. Ship a release after changing either installer.

## Practical notes

- Stack: Python 3.11+, pydantic v2 at the serialization boundary, pytest + hypothesis,
  ruff. Keep dependencies minimal.
- Clean-room reimplementation of dex-core invariants: do **not** import from or depend on
  dex-core. Reading it for pattern reference is fine.
- macOS-specific enforcement (e.g. sandbox-profile assertions) must be written behind a
  Linux-testable abstraction; the CI matrix covers macOS.
- Run `python -m pytest` and `ruff check .` before committing.
