# Dex Lens — build and delivery status

Last updated: 2026-09-01. Plain-language companion to
`docs/handoff/HANDOFF.md`, which remains the binding product and safety plan.

## Significant capability coverage contract, 2026-09-01

The Lens catalogue contract is implemented and locally verified: older
family-free signed catalogues remain valid, while new catalogues may carry
closed capability aliases, outcome families, typed component references,
complete MCP tool inventories, and declarative automatic/manual-only
assessment metadata. Family availability is derived from signed member
entries; it is never stored as a second status.

Core publication is held until this exact Lens contract has been reviewed,
merged, and released under a tagged Lens version. No Core catalogue signing or
public catalogue update is enabled by this local implementation.

## First look is the default, 2026-08-28

The first-look skill fix is **live as signed Lens v0.1.15**. GitHub
Release `v0.1.15` is latest (source commit `d009a8d`, run
`33167244234`). The public one-line install serves
`DEX_LENS_VERSION=0.1.15`. The repository `install.sh` was not
hand-edited.

Dave's first vault run after v0.1.14 still opened as a delta against
yesterday's leftover report, even after "Ignore last report" and
"pretend it's your first time." That habit lived in the skill, not the
browser path v0.1.14 fixed.

What v0.1.15 changes: a first look is the default. "What Dex has that I
don't" starts Phase 1 on the open folder. `dex-lens reports --last` runs
only when they ask what changed. "Ignore last report", "first time", and
"fresh eyes" win over a report sitting on disk.

## Deterministic diagnosis engine candidate, 2026-08-27

The engine and chat-native approval first went **live as signed Lens
v0.1.14**. Dave approved publication on 2026-08-28. GitHub Release
`v0.1.14` is source commit `7aa1587`, run `33166503410`. The public
one-line install then served `DEX_LENS_VERSION=0.1.14`. The repository
`install.sh` was not hand-edited.

What v0.1.14 adds: scope approval stays in the same chat
(`dex-lens diagnosis approve`). The local folder-picker page is
unchanged.

What the engine already owned in v0.1.13:

- ledger-derived report facts and a typed `ReportModel` bound to run identity
- closed decision and share receipts (preview is not sent)
- immutable run identity, closed stage machine, atomic checkpoints
- bounded specialist proposals and two-fold sceptical reconciliation
- `DeterministicDiagnosisEngine` as the only orchestrator
- process-default ports so real `dex-lens diagnosis` / `dex-lens-mcp` can run
- persisted local scope approval so later commands can collect after prepare
- JSON CLI (`dex-lens diagnosis`) and read-only MCP (`dex-lens-mcp`)
- skill text that follows engine `status` / `advance` / `result`
- golden replay: direct, CLI and MCP canonical result bytes are identical

Local verification on this Cloud Agent VM, after the process-default engine:

- Engine-owned subset used for this pass (diagnosis, reports, evals except
  the known legacy-system mount-point crossings, skill, packaging, diagnosis
  consent, diagnosis import surface): **535 passed**, 3 deselected, 0
  failed. Golden replay no longer assigns the read-only
  `consent_authority` property.
- Full `tests/` collection still has the known Cloud-VM fixture-tree /
  mount-point crossings in adapter snapshot, inventory CLI, hostile G1
  fixtures, the contained full journey, and the legacy-system filesystem
  eval. Those guards were not weakened. GitHub CI remains the authority
  for that containment matrix.
- GitHub CI on `572f2d8` is green: Ubuntu and macOS 3.11/3.12 pytest,
  G1 bind-mount, M3 egress, M5 contribution egress, Section-6 live
  bridge, and the exact pilot-build G1–G6 + R3 gate. The earlier macOS
  red was only
  `test_a_piped_dry_run_says_what_it_would_do_and_does_none_of_it`: the
  test sealed PATH to `/usr/bin:/bin`, which hides setup-python on
  macos-14. The live installer was not changed; the test now keeps a
  3.11–3.14 interpreter on that sealed PATH so it still hides assistant
  choosers. Chat-native approval is on `main` as v0.1.14. The
  checklist is
  `docs/superpowers/plans/2026-08-27-dex-lens-diagnosis-engine-publication-checklist.md`.
- Ruff: clean on `src` and `tests`.
- Inventory: **777** fields; **151** stored with registered deletion paths;
  **1** transmitted through closed reviewed paths.
- Privacy grep: no real `/Users/<name>`, `/home/<name>`, or session URL in
  product or replay artifacts. The invented canary
  `INVENTED_SESSION_CANARY_NEVER_RETAIN` is a test input only and is absent
  from fingerprints, checkpoints, reports and MCP messages.

Draft implementation PR: https://github.com/davekilleen/dex-lens/pull/46
Design PR: https://github.com/davekilleen/dex-lens/pull/45
Mission Control: davekilleen/dex-cards#99

## Signed release and complete live reference, 2026-08-27

Lens v0.1.14 is the signed public download for Apple Silicon Mac and
Linux x86_64. It includes the deterministic diagnosis engine and
chat-native scope approval. Its reader accepts both the earlier
skills-only catalogue and the complete four-kind contract.

Core v1.97.2 now publishes that complete signed reference at the live catalogue
route: 115 entries covering 94 skills, 11 connection systems containing 146
individual tools, 5 recurring jobs that run on a schedule, and 5 behind-the-scenes
services. The released Lens v0.1.14 verifier accepts the live bytes using its built-in key.
The application and its reference data are released separately on purpose:
Core can keep the reference current without requiring a new Lens download.

This is release proof, not participant-outcome evidence. No real participant
pilot has run yet.

## The experience pass: one install, and a report that survives, 2026-08-24

The skill worked and the experience around it did not. Five changes, all on
the same theme: what a person actually touches.

**One action to install.** Getting to the first insight meant a clone, a
virtual environment, a pip install and a hand-copied skill folder. `install.sh`
at the repository root does all of it from one line, builds the command its own
Python environment so nothing else on the machine can be disturbed, is safe to
re-run, and has a `--dry-run` that says exactly what it would do and does none
of it. It reports what it changed rather than what it intended to change, and
fails loudly instead of leaving half an install behind.

**A report that outlives the conversation.** A second opinion held only in a
chat window is gone by Friday, and the next run has nothing to compare against,
so it repeats findings the person already acted on. Every diagnosis now ends
with `dex-lens reports save`, which writes a dated Markdown report to
`~/.local/state/dex-lens/reports/` — app storage, never the inspected folder,
and the command proves that separation before it writes. `dex-lens reports`
lists what is there; `dex-lens reports --last` gives the next run its baseline,
and exits non-zero when there is none so "first run" is distinguishable from
"nothing changed".

**Evidence that cannot be skipped.** The skill now carries the exact report
template, and the rule that makes it work: every scored line carries a quoted
line from a file that was actually read, with its path. No quote means the
label is Unknown. An unread skill cannot be scored, and a scored finding with
no quotation under it is a defect in the report rather than a style choice.

**Contradiction hunting as a method.** The most valuable finding on the
reference vault was an instruction file banning a calendar tool that at least
eight skills, including the one that runs every morning, still call by name.
Nothing surfaces that by accident. The skill now has the method — extract the
hard rules from the instruction files, turn each into something searchable,
search the skills for it, report both sides quoted — with the calendar case as
an illustration rather than a special case.

**Narrowing, and a recurring check with no number to remember.**
`dex-lens catalogue --jobs <ids>` and `--only <ids>` scope the digest once the
person's jobs are known, and refuse rather than print an empty list when a name
is wrong. `--since-last` compares against the catalogue version this machine
was last shown, records the new one after every run, and prints nothing when
nothing has changed.

**The evidence rule, enforced rather than requested.** `dex-lens reports save`
now refuses a report that has not shown its work: it must say what was read,
say what happens next, quote at least one line from a real file, leave no
scored finding standing with neither a quotation nor an honest "Unknown", and
pair any shortlist with the rejections that prove a comparison happened. It
names what is missing and writes nothing. `dex-lens reports check` gives the
same answer without saving. A rule that lives only in a skill's prose holds
until the run is long and the assistant is tired, which is exactly the run
where a thin diagnosis does the most damage.

The read-only promise is now also proven across the *sequence* a person runs,
not only per component: `tests/test_read_only_promise.py` fingerprints every
file in a small system, runs the inventory and saves a report about it, and
fails if a single byte inside the inspected folder moves.

**A real delta, computed locally.** The first pass at the recurring check could
only say "the catalogue moved", because published entries record the Dex Core
release they changed in, not the catalogue version. That turned out not to
matter: what *this machine* has seen is knowable here. `dex-lens catalogue`
now fingerprints every published entry when it shows it and keeps the
fingerprints in app storage, so `--since-last` answers with the new ones, the
reworded ones and the names of any withdrawn — and prints only those. Nothing
is asked of Dex, and only public catalogue text is fingerprinted.

**A second look must account for the first.** Once a report exists for a
system, saving another one requires a section saying what changed — "nothing
has changed since then" is a complete answer, leaving it out is not. A
recurring diagnosis that restates the same findings every time is how a person
learns to stop reading it.

**And the first thing anyone types.** A bare `dex-lens` used to answer with an
argparse usage error about the frozen browser journey. It now says what Lens
is, that it is used by asking your assistant rather than by running commands,
and what the four commands are for.

### Four defects found in review, 2026-08-24

Found by review of the branch above, all fixed with a test that fails without
the fix. Recorded here because each one is a lesson about where these tests
were pointed rather than a slip.

1. **The documented install crashed.** `curl … | bash` has no file on disk, so
   `${BASH_SOURCE[0]}` is unset and `set -u` refused it — the one invocation
   shape the README tells people to use was the one nothing ran. The dry run
   exited before reaching that line, so a green test suite proved nothing about
   it. Source resolution now happens before the dry run (which says which of
   the two it would be), the expansion is guarded, and the tests pipe the
   script into `bash` the way the README does.
2. **A same-second second report lost its label.** The collision counter was
   appended after the label, and the parser reads everything after `--` as the
   label, so the newer report filed itself under `vault-2`: the listing missed
   it and the next run compared itself against the wrong baseline. The counter
   now sits after a character a label can never contain.
3. **"Unknown" anywhere waived the evidence rule.** The waiver was a substring
   test, so "it calls an unknown tool" — a confident, specific, unquoted claim
   — passed the gate that exists to stop exactly that. It now matches an
   Unknown *label*, where the template puts labels.
4. **`reports check` was a false green light.** It skipped the "account for the
   last look" rule that `save` enforces, so it approved reports `save` then
   refused. Both now call one gate with the same inputs.

### Closing the last two gaps, 2026-08-24

**The contradiction hunt is now enforced, not encouraged.** It was the most
valuable finding on the reference vault and the easiest to quietly skip, so a
report must carry the contradictions section and show that the search happened:
either a conflict with the rule and the thing breaking it both quoted, or the
plain sentence saying the rules were checked against the skills and nothing
conflicted. An empty heading is refused. Finding none is a real answer; silence
is not.

**`dex-lens inventory --names`** lists only the items whose name contains what
you ask for, so a second look can pull the three things the last report flagged
instead of all two hundred and sixty. Narrowing hides rows, never facts: the
counts and every housekeeping finding still describe the whole folder, the
document says so at the top, and a name nobody has is refused rather than
answered with an empty list that would read as an absence.

### The residual gaps, stated honestly

The local delta has two limits, both said in the command's own output and in
the skill. It compares against what this machine has seen, so a capability
that changed before Lens first ran here looks unchanged from here. And a
fingerprint moves when the published text moves, so a tidied-up summary counts
as a change; better a cosmetic change reported than a real one dropped. A
delta that survives a fresh machine — "new since catalogue version 3", for
anyone, on first run — still needs Dex Core to stamp each entry with the
catalogue version it first appeared in.

Two smaller limits worth recording. The installer is a *source* installer from
the public repository, not the signed release bundle described below; that
distinction is now stated in README rather than glossed. And no test performs a
real install: the tests check that the script parses, that its destructive
lines name computed destinations, and that `--dry-run` changes nothing, because
proving a real run belongs on a clean machine rather than in a unit test that
would have to write into the developer's live system.

## The product is a skill now, not a web application, 2026-08-21

Dave's decision, after watching the first real-machine run.

The browser journey asked a person to fill in six free-text fields per
inferred job — success evidence, three kinds of limit, importance, cadence —
before showing them anything at all about their own system. It asked them to
explain their system to the tool as the price of the tool explaining their
system back. Nobody fills that in.

Underneath the forms was a sound idea: the Success Contract is how the
product earns the right to say "Verified" instead of inventing its own
standard for what "working" means. The principle survives; putting it in a
form at the start does not. The skill infers, shows its reasoning, and lets
the person correct it by exception.

The deeper reason is that the analysis was in the wrong place. The comparison
the product exists to make is a judgement about the *content* of hundreds or
thousands of files. Filename matching cannot make it — that is why the
Capability Map came back all-Unknown on a real vault. An assistant reading
those files can. So the analysis moved into the person's own assistant, and
what stays in Python is what a prompt should not be trusted with: verifying
the catalogue signature, and folding a 6,417-file system into 53 KB that fits
in a context window.

What this costs: the sandbox proved the browser journey could not write,
execute or reach the network, because a person had no reason to trust a
program they had just handed their files to. Inside their own assistant there
is no separate program to guard against, so most of that concern disappears
rather than being ignored — but the *provable* version of the promise goes
with it. The rest of the boundary still applies and is applied: same
allowlist, same credential deny list, secrets redacted, bounds reported
honestly, and no writes.

**The browser journey is frozen, not deleted.** It works, its tests pass, and
it keeps the catalogue and safety code the skill depends on. No further work
is planned on it. Decide whether to remove it once the skill has proved
itself on real people.

Decisions taken with it:

- The skill **never writes** to the person's system. It hands over a brief;
  applying it is a separate decision they make with the brief in front of
  them. The read-only guarantee stays whole.
- It lives in `dex-lens`, not inside Dex Core, so someone with a homegrown
  setup can get a second opinion without adopting Dex. That was always the
  point.

See `docs/skill-README.md`.

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

Dex Lens is now released, but the pilot has not happened. Lens v0.1.15 is the
signed public download for Apple Silicon Mac and Linux x86_64. Its release
workflow built fixed offline bundles, signed the exact manifest, installed
without administrator access, and passed clean consumer proofs on both
platforms before publication. No observed participant evidence exists yet.

The **live capability bridge** — the consented connection from a person's own
system to Dex's signed release catalogue — is built, merged, released, and
proven live. The section-6 evidence pack (`docs/pilot/bridge-evidence.md`)
preserves the earlier skills-only proof as history. The current signed
catalogue is published by Core v1.97.2 at
`https://heydex.ai/catalogue/dex-lens/v2.json`; released Lens v0.1.15 accepts
all 115 entries across the four kinds described above. The privacy boundary is
unchanged: a fresh install makes no catalogue request, while a person who asks
for the Dex comparison receives the same public reference as everyone else.

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

1. Publish a release carrying the installer fixes. The self-serve release
   workflow is merged, its dedicated signing key is configured, and v0.1.4 is
   published with both platform archives, its manifest, signature and public
   key. The remaining half of this item was verifying the one-line installer
   against the **served** bytes rather than the repository's copy, and doing
   so found two defects the repository's copy does not have: the served
   installer parses no arguments at all, so the documented `--dry-run`
   performs a full install, and it never warns when `~/.local/bin` is off
   `PATH`, so the line it prints for the person to paste can start an
   assistant that cannot find `dex-lens`. Both are fixed in this branch and
   reach a user only when the next release is cut and re-rendered.
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
