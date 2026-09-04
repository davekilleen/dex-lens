# Adversarial review brief — external pass (Codex), 2026-09-03

Prepared for the founder to hand to an external review agent, verbatim. The
review target is public repository content only; no inspected-system material
belongs in the reviewer's context.

---

Adversarial review of github.com/davekilleen/dex-lens, branch
`codex/lens-significant-capability-coverage`, commits after `5f05ee2` up to
and including `c3deb3b` only.

The governing standard is
`docs/superpowers/plans/2026-09-03-dex-lens-wow-gate-completion-goal.md` —
read it first. This programme previously shipped a fully green suite in which
a diagnosis that determined nothing scored 91/100, because its tests asserted
things true by construction. Your job is to find where the new code fails its
own standard. The authors believe they followed it; assume some did not.

Hunt specifically for:

1. **Tests true by construction** — assertions a type constraint, fixture, or
   the test's own setup already guarantees; tests that could never have
   failed; "red-first" claims whose red could only ever have been an import
   or attribute error rather than the guarded behaviour.
2. **Unreachable guards** — refusal branches no shipped input can reach.
3. **Retention and output leaks** — any path where inspected-system content
   (labels, relative paths, reasons, legend rows) reaches a commit-able,
   shareable, or transmitted surface. Attack the new `evidence_legend` end to
   end, the disputed-disposition reason sentences, the typed model refusals,
   the crash-log wiring, and the home-relative report location (symlinked
   homes; locations not under home).
4. **State machines with no exit** — any sequence of *valid* inputs that
   leaves a run un-completable and un-abandonable. Attack the
   all-packets-at-once work issuance against the sceptical lock, disputed
   baselines against the two-attempt retry protocol, the truncated evidence
   union against ranked-recommendation derivation and insight trimming, and
   compare re-derivation against a run resumed after upgrade.
5. **Authority laundering** — any way a specialist proposal, sceptical
   response, stored artifact, tampered file, or the family-contract path
   becomes a conclusion without engine-minted evidence. Can a sceptical
   response smuggle in a disposition or factors nobody proposed? Does any
   derivation invent recommendation factors?
6. **Determinism** — any new path where input ordering changes output bytes.

For every finding: reproduce it with a concrete invented fixture, cite
file:line, and rank it — A: invalidates a run's score or leaks content;
B: wedges or misleads a run; C: weakens the test suite's honesty. Also list
the attacks you tried that failed. Do not fetch or use any real vault
content; everything must be reproduced with invented fixtures.
