# Goal: every Wow Gate task built and demonstrated

**The goal.** Every task in the autonomous Wow Gate programme is finished only
when its behaviour is *demonstrated* — each acceptance criterion proved by a
test that has been observed to fail without the code it guards, and by a run of
the real shipped command rather than a stand-in.

That wording is deliberate, and it is the whole point of this document. "Built"
and "green" were both true of this programme on the morning of 2026-09-03, and
neither meant what it appeared to.

## Why the goal is worded this way

On 2026-09-03 seven independent reviews examined Tasks 4–10, which had been
implemented and had a fully green suite. What they found:

- A diagnosis that determined **nothing** — all fourteen significant families
  `UNKNOWN`, no observations, every claim citing a fabricated evidence identity
  — scored **91/100 and passed** through the shipped grader, with zero hard
  failures. An honestly evidenced run scored 92. The gate could not tell them
  apart.
- The headline hard failure, "a human wrote the proposals", was **unreachable
  by construction**: it gated on a field whose type is a single-value literal.
  Its test passed only by handing the grader a `SimpleNamespace` the engine can
  never produce.
- `_validate_ledger_insights` refused an insight with empty evidence, which the
  model's own `min_length=1` already prevents. It could never fire.
- `_workflow_quality` tested a condition `Field(min_length=2)` guarantees, so it
  counted edges.
- The privacy canary was defined and **never planted anywhere**, and one
  assertion stated outright that the input contained no canary.
- Two "honest" test fixtures cited two evidence identities while recording one.
- 26 tests failed when their files were run alone; the suite hid it through
  import order, and CI could not catch it because CI runs the whole suite.
- The grader's second input had **no producer in any shipped surface**, so the
  acceptance loop could not be run as written.

None of that was carelessness about testing. There were many tests. They
asserted things that were true by construction, so they ran green forever while
proving nothing. A programme cannot detect that from inside its own suite,
which is why this goal makes the failing observation mandatory rather than
assumed.

## What counts as built

A task is built when its behaviour exists in `src/` or `scripts/`, reachable
from a shipped surface — the CLI, the MCP server, or the packaged skill — and
not only from a test. Code no shipped path can reach is a prototype.

## What counts as verified

All six, for every acceptance criterion:

1. **The test has been seen to fail.** Run it against the tree without the
   change and observe red, or revert the change and observe red. A test never
   observed failing is an assertion about nothing.
2. **The failure names the right cause.** A test that goes red for an unrelated
   reason — a fixture that will not build, an import error — has not been shown
   to guard anything.
3. **No tautologies.** A criterion is not verified by restating a type
   constraint, a model validator, or a module constant back to itself. If the
   type already guarantees it, the test proves the type, not the behaviour.
4. **Real types, not stand-ins.** If the only way to reach a branch is an object
   the engine cannot produce, the branch is unreachable and must be either made
   reachable or **withdrawn in writing**. An unreachable guard is worse than no
   guard, because it reads as protection.
5. **The shipped command runs.** Each task's entry point is exercised end to end
   through the surface a person or host actually uses, with its real inputs.
6. **Green alone, and green in isolation.** The full suite passes, and every
   changed test file passes when run on its own.

## Scope, in order

**Tier 1 — a trustworthy first number.**
`docs/superpowers/plans/2026-09-03-dex-lens-trustworthy-first-number.md`,
Tasks 1–4: honest scoring, a bound audit input, a canary that is actually
planted, and a CLI that guards what it prints. Tasks 1 and 2 are complete.

**Tier 2 — the three findings that block release whatever a score says.**
The rows in `docs/RISK-REGISTER.md`: guided comparison trusting a stored
artifact it never re-derives; the aggregate-limit wedge that leaves an ordinary
run with no exit; and `for_catalogue` dropping six fields on reload so a
tampered ledger passes `report check`. The wedge is the likeliest of the three
to be met by the first real run, because it is triggered by specialists citing
two pieces of evidence each — which is what good specialists do.

**Tier 3 — the original programme.**
`docs/superpowers/plans/2026-09-02-dex-lens-autonomous-wow-gate.md`, Tasks 6–12,
re-verified against this goal rather than against their original green suite.
Task 6 is the largest: the discovery adapter never emits the attributes the
workflow graph keys off, so the graph is empty on any real system and the
feature does not work outside its own fixtures.

## How we know the goal is met

- The fabricated ledger recorded in the Tier 1 plan scores below 90 and fails;
  an honestly evidenced ledger passes.
- A deliberately planted canary is proved absent from all eight surfaces, having
  first been proved to reach the report without the guard.
- Every hard failure the programme names either fires in a test or is withdrawn
  in writing, with the reason recorded.
- The acceptance loop runs from shipped commands with no hand-extracted input.
- A read-only evaluation completes against a real personal system without
  wedging, and only its aggregate grade leaves that machine.
- Full suite green; every changed test file green alone; `ruff check .`,
  `scripts/check_inventory.py` and `git diff --check` clean.
- No claim of completeness rests on a test that has never been observed failing.

## What this goal does not authorise

No merge, release, signing, catalogue publication, installer promotion, website
deployment, or production change. PR #53 and Core PR #689 stay draft. The
inspected system's name, paths, filenames, observations, report text, proposal
text and identifying counts never enter a commit, CI log, PR or shared
artifact — only aggregate scores travel.
