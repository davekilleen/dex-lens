# Adversarial review brief — external pass on the two-pass build, 2026-09-07 (evening)

Prepared for the founder to hand verbatim to an external review agent or a
fleet of them (parallel reviewers are welcome: findings are independent).
Review target is public repository content only; nothing from any real vault
may be fetched or used — every reproduction uses invented fixtures.

---

Adversarial review of github.com/davekilleen/dex-lens, branch
`codex/lens-significant-capability-coverage`, at the branch head (the commit
carrying "the non-lineage job axis" and everything before it).

The governing standard is
`docs/superpowers/plans/2026-09-03-dex-lens-wow-gate-completion-goal.md` —
read it first, then `docs/RISK-REGISTER.md` end to end: every row is patched
ground worth re-attacking, and the newest rows (RISK-COLD-PASS-2026-09-04,
RISK-EXTERNAL-PASS-2026-09-07) were found by passes exactly like yours. The
morning pass on this same day found six exploitable defects, two of them in
code written that day to the same standard you are auditing; assume today's
~9,000 new lines contain more.

**The new attack surface, all landed today** (design:
`docs/superpowers/plans/2026-09-07-dex-lens-10x-experience.md`):

1. **The family map** — `DiagnosisStage.FAMILY_MAPPED`, `FamilyMap` /
   `FamilyMapRow` (run.py), `build_family_map` (expectations.py), the
   `diagnosis map` CLI and MCP read tool. Claimed: re-derived on every read,
   forged stored maps ignored and refused at compare, pre-stage saved runs
   still complete. Attack the tolerance path: can a run's map be made to
   disagree with its ledger? Can the pre-stage tolerance be used to skip the
   stage on a NEW run?
2. **Loud not-gated expectations** — `ExpectationState.NOT_GATED` rows on
   family-free catalogues; wow-gate `missing-expectation` vs zero-scored
   loud rows. Can a not-gated row be dressed as determinate, or vice versa?
3. **The authorship axis** — `ObservationOrigin` derivation (never stored,
   re-derived), STRENGTH/RECIPROCAL refusal without an authored citation,
   `unique_to_you` on the ledger. Attack the derivation table: can a stock
   Dex item be made to look authored (or an authored one stock) through
   signed-identity-key edge cases, alias collisions, or `server.tool`
   tokens? Can `unique_to_you` leak or be padded?
4. **Coverage block, two voices** — `canonical_coverage_block` branches
   (map-coverage story vs confession) and `coverage_block_errors` /
   `_coverage_problems` in reports check/save. Can a report ship with the
   WRONG branch (confession suppressed on an under-covered run)? Byte-exact
   refusal bypasses?
5. **Release-gap derivations** — `FamilyReleaseDelta` on map rows,
   `VersionDistance.newer_release_ids`, `canonical_release_gap_block`, the
   loud Unknown branch. Attack lineage: can a fabricated release observation
   flip Unknown into "behind"? Is the "at least N" count launderable via a
   tampered stored ledger (the reload re-derivation is claimed to refuse)?
6. **FocusReceipt / FOCUSED mode** — engine-minted selection receipts,
   family-member packet slices, per-member coverage enforced at submit,
   compare and close; job-keyed variant on non-lineage runs (the receipt's
   family fields carry job ids there — attack that dual use). Can a
   selection be swapped after packets are issued? Can a focused run close
   with a silent hole via the disputed-member allowance? Can GUIDED runs be
   affected at all?
7. **JOB_COVERAGE and loan framing** — the closed kind's wire shape
   (`disposition = not-assessed` forced), lineage-run refusal, the
   non-lineage threshold (`is_non_lineage` — one kind-qualified match
   defeats it), report delta-claim refusal patterns (`behind Dex`,
   `releases behind`, `new since your`). Attack the threshold boundary and
   the pattern-matching: an honest delta phrasing that trips it, or a
   dishonest one that slips it?
8. **Live progress** — `WorkReceipt.recorded_at` outside digest/replay
   identity, `WorkProgress`/estimate absent-until-evidence. Can timestamps
   perturb replay idempotence or leak across runs? Can the estimate be
   made to appear with zero completions?
9. **The two-pass wow gate** — `pass_one_completeness`, `unpriced-unknown`,
   `sampled-selection`, focused-denominator coverage scoring. The register's
   history is fabricated ledgers outscoring honest ones: build the best
   fabricated ledger you can against the CURRENT gate and report its score.
10. **Selection memory** — `selection_memory()` parsing saved reports'
    decisions sections (bounded-slug regexes). Attack the parser: can a
    crafted report body forge memory (fake share-back fates, fake
    selections) that steers the next run's opening?

Hunt classes, same as always: tests true by construction; unreachable
guards; retention/output leaks (inspected-system content reaching outbound
surfaces — the local report may quote labels/relative paths, share-back and
grade JSON must not); state machines with no exit (valid inputs wedging a
run un-completably — today added three new stages/receipts); authority
laundering (stored artifacts trusted over re-derivation ANYWHERE);
determinism (input order changing bytes).

For every finding: reproduce with a concrete invented fixture, cite
file:line, rank A (invalidates a score or leaks content) / B (wedges or
misleads) / C (weakens test honesty). List attacks that failed. Hand back
findings as text; fixes happen on this side with red-first reproductions.
