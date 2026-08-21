# Dex Lens — build and delivery status

Last updated: 2026-08-21. Plain-language companion to
`docs/handoff/HANDOFF.md`, which remains the binding product and safety plan.

## First real-machine run, 2026-08-21

Until this date every check had run in CI or against synthetic fixtures. The
first run against a real, heavily customised vault on a real Mac found four
defects that no green matrix had caught, all now fixed with tests:

1. The deep adapter refused on every Homebrew-Python Mac — the Seatbelt exec
   allowlist named an unresolved interpreter path, so the contained child died
   before it started (`RISK-MAC-INTERPRETER-LITERAL`).
2. Availability demanded a no-network proof label macOS provably never emits,
   so even a working Mac fell back to the guided path
   (`RISK-MAC-SOCKET-CREATION`, now closed as an accepted asymmetry).
3. The capture bound was spent in walk order, so the presence probes described
   1.4% of the approved scope while reporting `healthy`, and claimed `absent`
   for files the collection had never reached
   (`RISK-BOUNDED-CAPTURE-ABSENCE`).
4. The capability shelf compared the adapter's implementation id against the
   catalogue's host family, reporting the person's host as unsupported for all
   55 published capabilities.

Together, 1 and 2 meant no Mac could ever have produced a Verified diagnosis,
on the only platform the product supports. The lesson is recorded here rather
than in a commit message: a green cross-platform matrix and 1,291 passing
tests did not substitute for one run on one real machine against one real
system, and the pilot plan should treat that run as a gate in its own right.

## The short version

The six-milestone product candidate is built and merged. M1–M3 merged first;
M4–M6 and their final security remediation merged to `main` in PR #5 on
2026-08-10 (`e139242`) after the Linux/macOS matrix, 1,291 local tests, lint,
packaging and data-inventory verification were green on the exact candidate.

This does **not** mean Dex Lens is released or that the pilot has happened.
The public doorway and signed release machinery are now implemented on the
self-serve launch branch: Lens can open a native folder chooser without scanning
or reading the selected folder's contents, and the release workflow builds fixed offline bundles,
signs their exact manifest, installs without administrator access, and runs
clean consumer proofs on Apple Silicon Mac and Linux x86_64 before publication.
The Linux installer rehearsal passed locally. There is still no published
release or supported participant download: the branch must pass GitHub review,
the dedicated release-signing key must be configured through GitHub's encrypted
secret route, and both real release smoke jobs must pass before the one-line
command appears at the top of README. No observed participant evidence or
completed independent sign-off exists yet.

The **live capability bridge** — the consented connection from a person's own
system to Dex's signed release catalogue — is built, merged, and proven live.
The section-6 evidence pack (`docs/pilot/bridge-evidence.md`) records the full
proof: the signed catalogue from Core release v1.96.1 is served at
`https://heydex.ai/catalogue/dex-lens/v2.json`, verified on-machine against the
pinned production key, exercised end to end by three representative non-Dex
host fixtures, with packet-level evidence that a fresh install makes zero
requests and a subscribed one makes exactly one per run. Dave approved the
public availability claim on 2026-08-12. All 55 capabilities across 11 jobs are
published and accepted by Lens: Wave 2's everyday set plus Wave 3's adoptable
role packs and optional career and quarterly-planning capabilities
(design: `docs/superpowers/specs/2026-08-11-dex-lens-live-capability-bridge-design.md`).

## Milestones

1. **M1 — safety foundation: merged.** Containment, evidence rules, the data
   boundary, hostile fixtures, and conformance gates are in place.
2. **M2 — diagnosis engine: merged.** Job Map, Success Contract, high-impact
   job taxonomy, diagnosis, and jobs-first Capability Map are in place.
3. **M3 — local read-only concierge: merged in PR #4.** The local browser
   journey, editable confirmation, session security, cancellation, guided
   fallback, and formal egress evidence are built. Deep inspection fails closed
   to the guided path on a host that cannot prove no-write, no-exec and
   no-network before any read. macOS proves no-network at the connect layer
   rather than the socket-creation layer; both are accepted, and the label the
   host actually produced is what gets shown (see the risk register, 2026-08-21).
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

1. Merge the reviewed self-serve release workflow, configure its dedicated
   signing key, publish the first exact release, and verify the anonymous
   one-line installer against the served bytes.
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
