# Dex Lens — build and delivery status

Last updated: 2026-08-11. Plain-language companion to
`docs/handoff/HANDOFF.md`, which remains the binding product and safety plan.

## The short version

The six-milestone product candidate is built and merged. M1–M3 merged first;
M4–M6 and their final security remediation merged to `main` in PR #5 on
2026-08-10 (`e139242`) after the Linux/macOS matrix, 1,291 local tests, lint,
packaging and data-inventory verification were green on the exact candidate.

This does **not** mean Dex Lens is released or that the pilot has happened.
There is no supported participant setup package, no published release, no
observed participant evidence, and no completed independent sign-off.

The next programme of work is the **live capability bridge** — the consented
connection from a person's own system to Dex's signed release catalogue. Its
design document is in founder review on a working branch; none of it is built
yet.

## Milestones

1. **M1 — safety foundation: merged.** Containment, evidence rules, the data
   boundary, hostile fixtures, and conformance gates are in place.
2. **M2 — diagnosis engine: merged.** Job Map, Success Contract, high-impact
   job taxonomy, diagnosis, and jobs-first Capability Map are in place.
3. **M3 — local read-only concierge: merged in PR #4.** The local browser
   journey, editable confirmation, session security, cancellation, guided
   fallback, and formal egress evidence are built. Deep inspection fails closed
   to the guided path when macOS cannot prove the stronger containment claim.
4. **M4 — safe adaptation boundary: merged in PR #5, not released.** Preview,
   approval, recovery, receipt, and undo are exercised on isolated synthetic
   files. Real-user automation refuses because Lens cannot yet observe the job
   outcome after real use; diagnosis and guidance remain available.
5. **M5 — optional contribution: merged in PR #5, not connected to a live
   intake.** Capability Cards, exact disclosure, fresh per-version consent,
   moderation, catalogue trust, withdrawal, and stage-nine user control are in
   place. Nothing is selected for sharing by default.
6. **M6 — pilot machinery: merged in PR #5; real pilot not run.** Enrolment, locked
   measurement, runbooks, red-team executors, exact-build release gates, and a
   fail-closed R7 completeness verifier exist. The verifier deliberately
   reports incomplete until real participant evidence and independent sign-off
   are attached.

## Verification state

- The full merged candidate is green on GitHub CI across Linux and macOS:
  PR #5 merged with eight green checks covering the matrix, the privileged
  bind-mount proof, the M3/M4 offline-egress proof, the M5 exact-byte egress
  proof, and the combined G1–G6 plus R3 release gate on the exact candidate.
- A local skip is recorded as **unproven**, never silently treated as a pass.

## What remains before invited testing

1. Prepare the supported tester handoff rather than asking participants to
   interpret developer instructions unaided.
2. Keep automated real-user adaptation disabled until a genuine later-use
   Success Contract outcome procedure exists; configuration presence is not
   outcome proof.

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
