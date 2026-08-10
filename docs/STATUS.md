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

The full test suite passes on Linux and across the supported GitHub Actions
matrix.

## The two loose ends before M1/M2 can be called truly closed

1. **macOS socket denial — honest asymmetry recorded and CI-verified.** Linux
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
   `CAP_SYS_ADMIN`, which this VPS and the standard hosted runner do not grant.
   Closing G1 honestly requires a dedicated, isolated Linux runner with that
   narrow privilege; the skip remains loud until one is available.

## Implemented and merged in PR #4

3. **M3 — the local browser concierge.** The source alpha now has the trusted
   `dex-lens` doorway; fail-closed loopback session security; cancellable,
   scope-revalidated collection; honest contained-host refusal; editable/addable/
   discardable Job Map drafts; full Success Contract confirmation; diagnosis;
   and jobs-first Capability Map rendering. The clean wheel/entry point, a real
   contained end-to-end journey with zero inspected-root writes, canary-leak
   checks, and completion with external connections refused are covered by
   tests on the branch.

   The guided/export-assisted diagnosis path is implemented for hosts where
   containment is unavailable. It accepts only bounded Supported, Reported, or
   Unknown evidence, then reuses the same editable Job Map, confirmation, and
   Capability Map journey without writing to the inspected root.

   The binding interfaces-disabled packet/DNS/proxy proof is now green in a
   dedicated Linux CI gate. It runs the full seven-page journey in a Docker
   `--network none` namespace, captures the loopback traffic, and fails on DNS,
   proxy use, non-loopback packets, unparsed packets, or canary leakage.

   **Closure status:** the bind-mount proof now has a dedicated Docker CI gate
   (`g1-bind-mount-gate`) that runs the hostile module with only `SYS_ADMIN`,
   no network, a read-only root, and bounded writable `/tmp`; its JSON report is
   uploaded as `g1-bind-mount-evidence`. Ordinary local/matrix runs still skip
   loudly when the host cannot create the mount. On macOS the deep adapter now
   fails closed unless socket creation itself is runtime-proven; runners that
   prove only connect-time denial use the guided/export-assisted path.

   Until a green privileged CI artifact and a macOS socket-creation proof are
   observed, call this a read-only source alpha with explicit boundaries, not
   a completed M3 release.

   **Build authorization is recorded:** HANDOFF D0 was posted on Dex issue
   #347 on 7 August against the signed pack hash
   `de01cfb1794790a90e34010198063a8449631e32ec450b8f4368cc21ab7bf6f5`.

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

M3 is the first usable surface and its baseline is merged in PR #4; closure
evidence is tracked by the dedicated privileged bind-mount gate and the
fail-closed macOS selection test.
M4 is the most safety-critical. M5 and M6 depend on decisions in
`DAVE-DECISIONS.md` (moderation host, pilot recruits, consent review) more
than on code. The two M1 loose ends are small but one needs Dave's call.
