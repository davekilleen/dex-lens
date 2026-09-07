# Adversarial review brief — external pass, 2026-09-07

Prepared for the founder to hand verbatim to an external review agent (any
strong model). The review target is public repository content only; no
inspected-system material belongs in the reviewer's context, and nothing from
any real vault may be fetched or used — every reproduction uses invented
fixtures.

---

Adversarial review of github.com/davekilleen/dex-lens, branch
`codex/lens-significant-capability-coverage`, at the branch head. Two earlier
cold passes (2026-09-03 and 2026-09-04) found and fixed defects in the areas
recorded in `docs/RISK-REGISTER.md`; treat those areas as patched ground worth
re-attacking, not as cleared.

The governing standard is
`docs/superpowers/plans/2026-09-03-dex-lens-wow-gate-completion-goal.md` —
read it first. Every guarantee is supposed to be held by a test that was
observed to fail without the code it guards. Your job is to find where the
code fails its own standard.

Context that should sharpen your attack: the first full real-world run
(2026-09-07) closed cleanly and still under-delivered in two specific ways.
It assessed 21 of 115 catalogue entries, leaving 94 `not-assessed`, and it
labeled stock catalogue capabilities present in the inspected system as
`strong-here` (the person's standout strengths) instead of `shared`. Both are
now addressed by guidance and by sharpened packet questions
(`_ROLE_QUESTIONS` in `src/capability_exchange/diagnosis/work.py`, with a
`_SUPERSEDED_ROLE_QUESTIONS` allowance so stored runs survive the wording
change) — attack that allowance in particular: can it be used to substitute a
question, replay an old packet into a new run, or mint a packet digest the
engine did not issue?

Also new since the first draft of this brief: the founder approved the
significant-family contract, and that approval is recorded in
`scripts/generate_family_contract.py` (`_FOUNDER_RESOLUTION`), which now
emits every family's review with zero open TODOs. Attack the boundary this
must preserve: the resolved draft is still UNSIGNED and must never be
treated as release truth — verify that nothing in the Lens runtime accepts
the draft file, or any unsigned `capability_families`, in place of families
carried inside a signature-verified catalogue envelope; and check the
evolved test (`test_every_family_carries_the_founders_recorded_resolution`)
still holds the original guarantee rather than merely matching new strings.

Hunt specifically for:

1. **Tests true by construction** — assertions a type constraint, fixture, or
   the test's own setup already guarantees; "red-first" claims whose red
   could only ever have been an import error.
2. **Unreachable guards** — refusal branches no shipped input can reach.
3. **Retention and output leaks** — any path where inspected-system content
   (labels, relative paths, reasons, legend rows) reaches a commit-able,
   shareable, or transmitted surface. Attack the `evidence_legend`,
   disputed-disposition reasons, typed model refusals, crash-log wiring, and
   the home-relative report location.
4. **State machines with no exit** — any sequence of *valid* inputs that
   leaves a run un-completable and un-abandonable, including a run saved
   under a superseded packet question and resumed after upgrade.
5. **Authority laundering** — any way a specialist proposal, sceptical
   response, stored artifact, tampered file, or the family-contract path
   becomes a conclusion without engine-minted evidence.
6. **Coverage honesty** — the ledger reports `not-assessed` for unaddressed
   entries: can any path make an unassessed entry look assessed, or an
   assessed one disappear from the report?
7. **Determinism** — any new path where input ordering changes output bytes.

For every finding: reproduce it with a concrete invented fixture, cite
file:line, and rank it — A: invalidates a run's score or leaks content;
B: wedges or misleads a run; C: weakens the test suite's honesty. Also list
the attacks you tried that failed.
