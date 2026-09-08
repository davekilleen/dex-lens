# Dex Lens intake goal — ask the person first
2026-09-08 · Commissioned by Dave · Status: proposed

The compact goal condition submitted through /goal is derived from this
document; where they differ, this document governs.

## Outcome

Before Lens reads anything beyond the approved folder listing, it asks the
person a short set of fixed questions about their situation, records their
answers permanently in the run, and uses them to shape everything that
follows. After the report is saved — never before — it offers, as two separate
choices, to send those answers to Dave and to join the heydex.ai newsletter.
Declining either changes nothing about the report.

## The standard of proof (unchanged from the wow-gate goal)

A criterion counts as met only when a test proves it, and the test was
**observed to fail** on the tree without the code it guards. A test that
cannot be made to fail is withdrawn in writing. No criterion may be verified
by the agent reading its own diff and agreeing with itself.

## Definitions

- **Intake**: the question step. One engine stage, after scope approval,
  before any analysis planning.
- **Intake receipt**: the engine-minted record of the questions asked and the
  answers given. Typed, bounded, replayable — the same discipline as the
  existing focus receipt.
- **Attested**: a fact the person stated. **Verified**: a fact derived from
  the signed catalogue or the approved snapshot. The two are never presented
  with the same confidence and never silently substituted for one another.

## Criteria

### The questions (engine)

- **G1 — The intake stage exists and cannot be skipped.** A run cannot leave
  the intake stage until every question in its branch has a recorded answer.
  Proof: drive a run to intake, attempt to advance with one question
  unanswered, and assert a typed refusal that names the unanswered question.
- **G2 — "Not sure" is always an acceptable answer**, to every question, and
  a run answered entirely with "not sure" still reaches CLOSED. Proof: such
  a run closes. (Guard against the no-exit wedge class: a person must never
  be stuck because they don't know.)
- **G3 — Two branches, fixed questions.** "Do you have Dex installed?" —
  yes/no/not sure — decides the branch.
  - Dex branch: customisation level (barely touched / quite a bit /
    unrecognisable / not sure); first installed (last week / last month /
    last 3 months / at launch / not sure); last ran dex-update (last week /
    last month / longer ago / never / not sure).
  - No-Dex branch: built from an open-source project? (yes / no, built it
    myself / not sure); if yes, the project link; customisation level (same
    options).
  - Every answer is one of a closed option list. The only free text is the
    project link, bounded in length and validated as a URL. Proof: an answer
    outside the option list is refused typed; an oversized or non-URL link is
    refused typed.
- **G4 — Answers are stamped once and cannot drift.** The intake receipt is
  engine-minted, carried in the run, and re-derived on reload: a tampered
  stored receipt is refused. Identical answers produce a byte-identical
  receipt. Proof: tamper test (observed accepted before the guard, refused
  after) and a determinism test.

### What the answers may and may not do (report)

- **G5 — Attested framing, verified counts.** A report sentence resting on an
  intake answer says so in plain words ("you told me..."). Every release
  count and every family-level gap still derives only from the signed
  catalogue and the snapshot: a fabricated intake answer must not be able to
  change the number of releases the report says the person is behind.
  Proof: rendered-report assertions, plus a test that varies intake answers
  and asserts the verified counts are unchanged.
- **G6 — Disagreement is a finding, not a tiebreak.** If the person says "no
  Dex" while the snapshot carries Dex's release record, or says "yes" while
  it carries none, the report states both facts side by side and asks —
  neither answer silently wins. Proof: both directions rendered, observed
  missing before.
- **G7 — Plain words throughout.** No rendered sentence a person reads —
  intake questions, report, refusals — contains insider vocabulary. Banned
  list, enforced by a test over rendered output: "loan", "lineage",
  "non-lineage", "delta", "fingerprint", "ledger", "axis".

### Sharing and email (after the report, never before)

- **G8 — Nothing is sent without a yes, and the yes is informed.** The offer
  to share answers with Dave appears only after the report is saved. The
  person sees the exact content that would be sent, verbatim, before
  agreeing. Declining produces a byte-identical report and no network call.
  Accepting sends exactly the previewed bytes, through the same audited send
  path that guards share-back today. Proof: byte-equality on decline; an
  egress-evidence test in the M5 style proving the sent bytes equal the
  previewed bytes; a canary test proving vault content (a planted marker
  string) cannot appear in the payload.
- **G9 — The payload is the closed answer set and nothing else.** Question
  ids, chosen options, the project link if given, a timestamp, and the Lens
  version. No vault paths, no file names, no counts from the scan, no email
  address. Proof: schema-level (the payload model has no other fields) plus
  the canary test above.
- **G10 — Email is a separate choice.** Newsletter signup is its own
  question with its own yes; the email address travels only in the signup
  call the person approved and appears in no report, receipt, log, or
  intake payload. Proof: grep-style tests over every written artifact of a
  run that included an email.

### The receiving end

- **G11 — The Convex table and its contract live in the repo; the keys do
  not.** The repo carries the Convex schema and receiving function for the
  intake payload, and a contract test pins that what Lens sends validates
  against that schema. Deployment uses Dave's Convex account; no deployment
  key, URL secret, or credential enters the repo, CI, or any test. Proof:
  the contract test, plus the existing secret-scanning gate stays green.

## Fixtures

Every criterion is exercised against the stale-install fixture and its
no-Dex variant (tests/evals/stale_install_fixture.py), not against
minimal dioramas. The disagreement tests (G6) use both fixture variants
against both intake answers.

## Out of scope

- The authorship fix (defect 2) and the fixture migration recorded in
  RISK-NON-LINEAGE-COMPONENT-MATCH-2026-09-07.
- Any change to what the scan reads from disk.
- Any Dex Core (catalogue) change.

## Verification, run by the agent before claiming done

    .venv/bin/python -m pytest                      # full suite
    .venv/bin/python -m pytest <each changed file>  # every changed test file alone
    .venv/bin/python scripts/check_inventory.py     # every new field inventoried
    .venv/bin/python -m ruff check src tests scripts
    scripts/run_wow_gate.py fixtures unchanged or extended — never weakened

Plus one local run against the real vault clone with intake answers
simulated, reporting only aggregate outcomes.

## Done means

All criteria green in CI with their failing-first evidence linked in the PR;
the register carries no new open rows from this work (or names them with an
owner); the PR is held for Dave's review, not self-merged.
