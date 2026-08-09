# Dex Lens — build status and what's outstanding

Last updated: 2026-08-09. Plain-language companion to `docs/handoff/HANDOFF.md`
(the binding plan) and `docs/handoff/sources/gates.md` (the testable gates).

The plan has six milestones, M1–M6. Here's where each stands.

## Done and merged to `main`

- **M1 — the safety foundation** (containment sandbox, evidence rules, data
  boundary, hostile-fixture harness). Substantially complete; two loose ends
  below.
- **M2 — the diagnosis half** (Job Map with propose-then-confirm and the
  `Inspection` state, the high-impact job taxonomy, the diagnosis engine, and
  the jobs-first Capability Map rendering).

940 tests pass on Linux; the full suite is green there.

## The two loose ends before M1/M2 can be called truly closed

1. **macOS socket denial — honest asymmetry recorded, waiting on CI.** Linux
   blocks socket creation outright. The macOS attempt (`system-socket` in the
   sandbox profile) was well-reasoned but the GitHub macos-14 runners
   disproved the stronger claim — they handed out AF_INET/AF_INET6 sockets
   anyway. The enforced Mac guarantee is now stated as: a socket fd may exist,
   but outbound use is denied at connect time before any egress. The test now
   fails if connect succeeds or reaches the network, and the risk is recorded
   in `docs/RISK-REGISTER.md` for Dave's explicit M1/M3 call. Everything else
   on macOS (writes, shell, exec) is enforced.

2. **The bind-mount fixture has never actually executed.** The fix is in and
   the defence reads the live mount table, but the test that *proves* it needs
   a privilege the VPS and possibly the GitHub runners don't grant. If it
   skips on CI too, we need a privileged container leg or a `sudo mount` step,
   or the G1 bind-mount gate stays formally unproven.

## Implemented on the M3 launch branch — awaiting PR/CI proof

3. **M3 — the local browser concierge.** The source alpha now has the trusted
   `dex-lens` doorway; fail-closed loopback session security; cancellable,
   scope-revalidated collection; honest contained-host refusal; editable/addable/
   discardable Job Map drafts; full Success Contract confirmation; diagnosis;
   and jobs-first Capability Map rendering. The clean wheel/entry point, a real
   contained end-to-end journey with zero inspected-root writes, canary-leak
   checks, and completion with external connections refused are covered by
   tests on the branch.

   **Not formally closed yet:** the source alpha does not yet implement the
   guided/export-assisted diagnosis path for a host where containment is
   unavailable. The integrated branch also still needs the full Ubuntu/macOS
   Python 3.11/3.12 CI matrix, and the binding M3 bar asks for an
   interfaces-disabled plus packet/DNS capture run. The current Linux proof
   combines OS-enforced socket denial in the collection child with a parent
   process test that refuses every non-loopback connection; it is strong but
   not the same artifact as host packet capture. Until those proofs exist, call
   this a read-only source alpha, not a completed M3 release.

   **Announcement gate:** HANDOFF D0 still requires Dave's recorded Fable-gate
   and two-stage handoff sign-off on Dex issue #347 before public publication.

## Not started — later product milestones

4. **M4 — the adaptation engine.** The transactional "make one change, with
   exact preview, proven undo, and a receipt" layer, gated behind all six
   safety gates plus fault-injection testing. The first point at which the
   product writes anything.

5. **M5 — the contribution flow.** Capability Cards, the disclosure manifest,
   the redaction/consent machinery, and the AI-led-with-Dave-approving
   moderation pipeline.

6. **M6 — the pilot.** Enrolment, locked measurement plans, the runbooks, the
   red-team pass, and the completeness pack. Needs the recruits and the
   consent review from `DAVE-DECISIONS.md`.

## Rough shape of remaining effort

M3 is the first usable surface and is now in integration review.
M4 is the most safety-critical. M5 and M6 depend on decisions in
`DAVE-DECISIONS.md` (moderation host, pilot recruits, consent review) more
than on code. The two M1 loose ends are small but one needs Dave's call.
