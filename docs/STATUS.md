# Dex Lens — build and delivery status

Last updated: 2026-08-10. Plain-language companion to
`docs/handoff/HANDOFF.md`, which remains the binding product and safety plan.

## The short version

The six-milestone product candidate is built. M1–M3 are merged to `main`;
M4–M6 and their final security remediation are integrated on
`programme/m3-m6-completion` in draft PR #5. The exact candidate commit has
passed the complete Linux/macOS matrix and every formal security evidence gate;
delivery review and merge remain.

This does **not** mean Dex Lens is released or that the pilot has happened.
There is no supported installer, no published release, no observed participant
evidence, and no completed independent sign-off.

## Milestones

1. **M1 — safety foundation: merged.** Containment, evidence rules, the data
   boundary, hostile fixtures, and conformance gates are in place.
2. **M2 — diagnosis engine: merged.** Job Map, Success Contract, high-impact
   job taxonomy, diagnosis, and jobs-first Capability Map are in place.
3. **M3 — local read-only concierge: merged in PR #4.** The local browser
   journey, editable confirmation, session security, cancellation, guided
   fallback, and formal egress evidence are built. Deep inspection fails closed
   to the guided path when macOS cannot prove the stronger containment claim.
4. **M4 — safe adaptation: built, not merged or released.** One bounded change
   can be previewed, approved once, recovered after interruption, verified,
   receipted, and undone. Diagnose-only remains the default.
5. **M5 — optional contribution: built, not merged or connected to a live
   intake.** Capability Cards, exact disclosure, fresh per-version consent,
   moderation, catalogue trust, withdrawal, and stage-nine user control are in
   place. Nothing is selected for sharing by default.
6. **M6 — pilot machinery: built; real pilot not run.** Enrolment, locked
   measurement, runbooks, red-team executors, exact-build release gates, and a
   fail-closed R7 completeness verifier exist. The verifier deliberately
   reports incomplete until real participant evidence and independent sign-off
   are attached.

## Verification state

- M3 is green on merged-main GitHub CI across Linux and macOS.
- The combined M3–M6 candidate passes 1,250 local tests, lint, and the data
  inventory on the Devbox.
- Exact commit `e27cc6b9cb0e6db4566797e7d2d286108e6bd84b` passes the
  GitHub Linux and macOS 3.11/3.12 matrix, privileged bind-mount proof,
  M3/M4 offline-egress proof, M5 exact-byte egress proof, and combined
  G1–G6 plus R3 release gate.
- A local skip is recorded as **unproven**, never silently treated as a pass.

## What remains before invited testing

1. Complete review and merge only after explicit approval.
2. Prepare the supported tester handoff rather than asking participants to
   interpret developer instructions unaided.

## What remains before the pilot can complete

- Recruit 6–8 regular Claude Code users on Mac, mostly people who do not use Dex.
- Review the consent, withdrawal, deletion, and incident wording.
- Name owners for every open risk and an independent safety reviewer.
- Run the pilot against the locked plan and preserve observed evidence.
- Complete the R7 evidence pack without substituting synthetic test data for
  participant outcomes.

The founder-owned actions are kept current in `docs/DAVE-DECISIONS.md`. The
Mission Control card must be updated in the same work session whenever this
delivery state changes.
