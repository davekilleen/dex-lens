# Working on Dex Lens

Read this before you touch comparison, authorship, coverage, or the report.
`CONTRIBUTING.md` already states the three rules that govern the code
(test-first, fail closed, binding vocabulary). This file exists for a
different reason: **the rules were right and we still shipped a report that
missed a 10-release gap.** What follows is what reality has taught us that
doctrine did not.

## 1. The job, in one paragraph

Dex Lens reads a person's own AI operating system, on their machine, and
tells them the truth about it: what they have actually built, how far behind
the Dex they could have they are, and what is worth taking. **The modal user
is months behind the current release and does not know it.** They installed
once, kept working, and their vault drifted while Dex shipped eighty
releases. A run that cannot make that gap undeniable has failed, however
many gates were green.

Corollary, and it is the whole product in one line: *the interesting user is
the stale user.* A current install is the easy case and the rare one.

## 1.1 The shape of a run: a lighthouse, not an audit

Lens is a **map of where value could be exchanged, in both directions**. It
is not an exhaustive inspection, and building it as one is the standing
temptation to resist. Two steps:

**Step one — light touch, fast, job-level.** Read the system at a high level
and put two things to the person, each as a multiple choice they can take
none, some, or all of:

- *Areas Dex could improve for you that you do not have* — and, for each,
  **why it would help their system specifically.** Not a feature list; a
  reason.
- *Areas you look strong in that Dex could learn from* — and which of those
  they would be willing to explore sharing back.

**Step two — deeper, only where they asked, with an estimate of how long it
will take.** They chose the areas; the depth is earned by their choice, never
assumed.

Three consequences the code must respect:

1. **Time to first value dominates.** Step one has to land in minutes. A run
   that reads every file to be thorough has failed the brief even if every
   claim is true.
2. **The unit is the job to be done, not the capability.** Differences worth
   naming are differences in what the system can *do for the person*.
   Capability ids churn across eighty releases; jobs do not. Job granularity
   is what survives a large version gap, which makes it the right altitude
   for the stale install as well as the right altitude for the person.
3. **Both directions are first-class.** "What Dex has that you lack" and
   "what you have that Dex lacks" are the same product, and neither is a
   footnote to the other. A run that only audits inward is half a product.

The detail from discovery stays available for an assistant to dig into
afterwards. Step one's job is to point at where digging is worth it.

## 2. The acceptance bar

A green suite is not evidence that a run works. What a run has to survive is
an install left alone for months while Dex shipped on — and that install has
structural properties our fixtures did not. A fixture earns the name "stale
install" only if it carries all of these:

| Property | Required |
| --- | --- |
| Files in the approved tree | thousands, not dozens |
| Skills present | ≥ 100, mixed authored / stock / assistant-vendored |
| Hooks present | ≥ 40 |
| `CHANGELOG.md` | an `[Unreleased]` section long enough to push the first version header tens of lines down |
| A `.dex-version` file | absent — no real install has ever carried one |
| Published catalogue capabilities post-dating the install | all of them |
| Distinct signed releases newer than the install | ≥ 10 |
| Local skills matching a signed catalogue identity | under a third |
| Local hooks matching a signed catalogue identity | none |

Every row of that table was measured on a real install and every row
contradicted an assumption in this codebase. Any change to comparison,
authorship, coverage or the report must be tried against a fixture carrying
them, and the assertion must be an outcome a person would recognise ("the
report headlines a gap of at least N releases"), not a shape.

The measured values themselves stay on the owner's machine — see §5. The bar
above is deliberately expressed as thresholds so this file never carries a
real system's identifying counts.

`tests/evals/legacy_system_fixture.py` does not carry them. It is a
twenty-file diorama with a clean three-line changelog, and it has never once
produced the failure modes a real stale vault produces. Passing it proves
almost nothing about the case this product exists for.

## 3. Failure ledger

Newest first. Each row is a belief reality contradicted. **Add a row every
time that happens — the ledger is the only artifact in this repo that
compounds.** Rows are never deleted, only annotated.

### F8 — "Not Dex" was inferred from the absence of name matches
*2026-09-07.* `canonical_job_axis_block` is the right answer for a person who
never installed Dex: one row per signed job, framed as a loan Dex offers
rather than a gap they are behind on, with no version to diff. Its trigger is
wrong. `is_non_lineage` fires only when *zero* observations match a signed
identity — "one signed-identity match, even a doubtful one, defeats the
classification" — and 85 of the catalogue's 117 capability ids carry no
namespace prefix: `journal`, `review`, `daily-plan`, `create-skill`,
`prompt-improver`, `meeting-prep`. A serious assistant user who has never
heard of Dex very plausibly has one of those names. That single coincidence
drops them onto the lineage path, where the release-gap block tells them to
approve a folder containing a Dex release file they do not have and run
again. A dead end, delivered to the population Lens most needs to convince.

The trigger must be evidence about Dex's *presence* — the provisioning
ownership contract, the Dex changelog sentinel, Dex's own module paths, all
of which exist at any install age and are absent when Dex is not installed —
never the absence of coincidental name matches. Three populations, three
honest voices: no Dex (the loan), Dex present but its version unreadable (the
priced Unknown, which only then makes sense), and Dex present with a known
version (the delta story).

### F7 — Absence of a signed match was read as evidence of authorship
*2026-09-07.* `derive_observation_origin` classified anything the current
catalogue does not name as `AUTHORED`, and `AUTHORED` is the only class that
may ground a strength or a share-back offer. On a stale install most of
*stock Dex* is absent from the current catalogue, so the report praised Dex's
own retired skills back to their vendor as the person's standout work — the
exact failure `ObservationOrigin`'s docstring says the axis exists to make
structurally impossible. Same bug pointing outward: `unique_to_you` would
have offered stock Dex skills back to Dex as the person's novel ideas.
Verified with the real vault: no local signal distinguishes a Dex-shipped
skill from an authored one — identical frontmatter shape, same directory, no
ownership marker, and the vault's plugin manifest enumerates servers, not
skills. **Lens cannot know locally.** So the honest third class is
"unattributed", and only a catalogue that publishes Dex's *historical*
identities can recover real authorship on an old install.

### F6 — Our fixtures shared the code's assumptions
*2026-09-07.* Every fixture in this repo was authored by whoever authored the
detector it feeds, so both carry the same blind spots. Red-first testing
removes tautological *assertions*; it does nothing about tautological
*worlds*. A real vault produced, on first contact, three defects no fixture
had ever produced. Guard: §2, and `scripts/vault_acceptance.py`.

### F5 — A gap claim degraded quietly, and the proposed fix over-reached
*2026-09-07.* When the reachable catalogue signed no family contract, the
release-gap block said "Nothing here claims your install is behind or
current" and moved on. That is a comparative claim failing silently, and
rule 2 of `CONTRIBUTING.md` already required it to refuse loudly instead;
having the rule was not enough, because nothing tested that the rule was
applied at this site.

The first proposed fix was to refuse the *whole report* in that state. The
founder rejected it as defeatist and was right: a thin catalogue is no
reason to withhold a true statement about the person's own system. That
over-reach is why §6 exists. Refuse the claim that lost its evidence, never
the claim that never needed it.

### F4 — A variadic flag swallowed the launch question
*2026-09-07.* `--allowedTools` consumed every following argument, so the
installer launched Claude with an empty prompt and the run died before it
began. Found only because a person watched it happen. Guard:
`test_the_claude_launch_puts_the_question_before_the_allowlist_flag`.

### F3 — Stored artifacts were trusted over re-derivation
*2026-09-07.* An unsigned stored `family_contract_present` flag was believed
at compare time. Guard: every consumer re-derives from the verified envelope
and refuses on disagreement (RISK-EXTERNAL-PASS-2026-09-07 A1).

### F2 — Worktrees were cut from a months-old base
*2026-09-07.* Parallel agents built against `main` while the work lived on a
branch; caught only by a schema inventory count mismatch (777 vs 995), after
a day of work had to be discarded. Guard: every agent brief opens with a base
check.

### F1 — The coverage voice confessed instead of covering
*2026-09-06.* The report announced how many catalogue entries it had *not*
assessed. The founder's response was the right one: insist on assessing
everything instead. Coverage is now computed over all fourteen signed areas
and the confession branch is reserved for genuine shortfall.

## 4. What reliably goes wrong here

Hunt these first, in review and in your own diffs:

- **Absence of evidence used as a positive finding** — the repeat offender in
  this repository, and F7 and F8 are the same bug pointing in opposite
  directions. "The catalogue does not name it" became "the person wrote it";
  "nothing matched a signed name" became "Dex is not installed". Whenever a
  branch turns *no signal* into a claim, name the third state instead:
  unattributed, unreadable, not established. Then decide what a person reads
  in it.
- **A name treated as a capability** — identity overlap is weak evidence and
  its failure mode differs by population. On a stale install a name match
  hides a real gap by crediting a years-old version as present. On a system
  with no Dex a coincidental match hijacks the whole report's voice. On a
  current install it is harmless, which is why fixtures built from current
  installs never catch either.
- **Authority laundering** — a stored artifact believed instead of
  re-derived. Anywhere.
- **Silent degradation** — a missing precondition producing a bland sentence
  instead of a refusal. Grep for the fallback branch and ask what a person
  reads when it fires.
- **Tests true by construction** — an assertion a type constraint or the
  test's own setup already guarantees.
- **State machines with no exit** — valid inputs that wedge a run
  un-completably.
- **Retention and output leaks** — inspected-system content on an outbound
  surface. The local report may quote labels and relative paths; share-back
  and grade JSON never do.
- **Determinism** — input order changing rendered bytes.

## 5. Non-negotiables

- The inspected system's name, paths, filenames, observations, report text
  and identifying counts never enter a commit, CI log, PR or shared
  artifact. Only aggregate scores travel. Evaluation runs on the owner's own
  machine; only the grade JSON returns.
- Never skip or disable a test to get green.
- Run every changed test file alone as well as in the suite.
- Never read, name, or suggest reading the user's own `~/.claude` directory.
  The vault folder is the whole permitted scope.
- No model identifiers in commits, PR text, code comments, or any other
  pushed artifact.
- Aggregate scores are computed by `scripts/run_wow_gate.py` against the
  standard in
  `docs/superpowers/plans/2026-09-03-dex-lens-wow-gate-completion-goal.md`:
  every criterion proved by a test observed to fail without the code it
  guards; unreachable guards withdrawn in writing.

## 6. The claim ladder

Three kinds of claim live in a report. They do not share dependencies, and
collapsing them is how a run either overclaims or goes mute when it had
something true to say.

**Local claims — "your system does this."** Evidenced entirely from the
approved snapshot: what is installed, what runs, what it is wired to, which
jobs it visibly serves. These depend on nothing Dex publishes. A thin,
stale, or unreachable catalogue is never a reason to withhold one. The
person's strengths are facts about their vault, and they were true before
Dex had a catalogue at all.

**Gap claims — "Dex has this and you do not."** These need a
signature-verified catalogue, because the claim is about Dex's contents, not
theirs. Every count ("at least N releases behind", "this area has M newer
capabilities") is a statement about the signed record. When that record is
unreachable or signs no family contract, refuse loudly and name the one
thing that would establish it. Never soften it into a bland non-claim.

**Reverse claims — "you do this and Dex has nothing for it."** The direction
the founder cares most about, and the one that finds what Dex should adopt.
They need the catalogue too — asserting absence requires knowing what is
present — but only at *job* granularity, which is the granularity the
catalogue publishes most robustly and which survives a large version gap
intact. A capability id renamed across eighty releases breaks a
capability-level comparison; the job it serves does not move. So when the
capability-level record is too thin to compare, the job axis is still
available, and a high-level reverse claim is still derivable. That is the
honest fallback: coarser, still true, never silent.

Applied rule: a run missing a family contract still reports local strengths
and still reasons about jobs. What it must not do is imply currency or
distance it cannot evidence.
