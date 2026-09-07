# Dex Lens 10x: the two-pass diagnosis

**Date:** 2026-09-07
**Status:** Design for founder review. Nothing here authorises merge, release,
signing, or catalogue publication.
**Provocation:** Today's first real user run took ~26 minutes, assessed 21 of
115 catalogue entries, left 94 entries silently `not-assessed`, produced
exactly one recommendation, praised stock Dex skills back at their own vendor
as the user's standout strengths, and told no release-gap story because the
family machinery was waiting on a contract signature.

That run was *honest by the engine's own books* and still a bad product. The
books balanced; the person waited 26 minutes for one idea and a compliment
about software they did not write. This document redesigns the experience
around a claim that is already latent in the codebase: **almost everything the
person needs in the first two minutes is deterministic and already
implemented — it just runs last instead of first.**

## The thesis in one paragraph

`assess_significant_families()` is pure, exact, evidence-bound, and needs no
language model. `assess_wow_expectations()` folds its output into six honest
states across all 14 families. `build_workflow_graph()`, the housekeeping
findings, `_version_distance()`/`build_family_delta()`, the automatic
candidates, and the skill-copy recommendation are all deterministic too. Every
one of them runs today inside `UnknownUntilProposedComparer.compare()` — at
the *end* of the run, after nine sequential specialist packets have spent 26
minutes re-reading the same full-width context. Invert it. Run the
deterministic layer first, show the person a complete 14-family map in under
two minutes with zero silent holes, let them multi-select the grey and
interesting areas, and spend the language model only where they pointed.
Pass 1 is the engine's arithmetic; pass 2 is judgement on demand.

## Fixed requirements (founder, 2026-09-07)

These three are constraints on everything below, not options:

1. **Full coverage inside a selected family.** When the person selects a
   family for pass 2, *every* member capability in it is rigorously assessed
   one by one against Dex Core. No sampling, and no silent `not-assessed`
   inside a chosen family — a member the dive genuinely could not settle is
   an explicit, reasoned, priced could-not-tell, and the engine refuses to
   close a focused run while any selected-family member lacks one of those
   two outcomes.
2. **The offer voice.** Neither pass is an audit of "to what extent does
   this person have these capabilities". The comparison speaks as Dex
   telling them what Dex Core has that they *appear not to have* — at family
   level in pass 1, capability level in pass 2 — with the benefit explained
   clearly and educationally: "this is how we think your system would
   improve by having X." Pass 1's version: "here is how your system could
   improve if you took a deeper dive into this area." Section 2a specifies
   how this voice coexists with the honesty standard; it does not relax it.
3. **Two reciprocal moments.** Unique features the person has that Dex does
   not are called out in pass 1, and after pass 2 the person is asked once
   more whether they would like to offer those ideas back to Dave at Dex —
   the idea only, never files or personal/company data, and only in exact
   words they approve first.

---

## 1. Experience narratives, minute by minute

### Persona A — an older Dex variant (the release gap is the story)

*Sam installed Dex fourteen months ago, ran `dex-update` twice, then stopped.
Their vault says `dex-core v1.89.0` in a release file the inventory finds.*

- **0:00** — "Have a look at my setup." Lens names the folder, one sentence.
  Sam says yes. `approve` records the receipt.
- **0:20** — Capture runs (bounded, read-only). Catalogue verifies. The
  engine builds the family map: exact identity matching of every observation
  against every signed family component, release identity extraction,
  per-family version deltas. No model tokens are spent.
- **1:30** — Sam sees the whole map, not a progress bar:

  > Your system is Dex, at v1.89.0 (Verified — your release file says so).
  > The current catalogue is v1.97.6. Here is every one of Dex's 14
  > significant capability areas, held against what I found:
  >
  > - **Meeting follow-through — you have this** (6 of 6 components
  >   matched; nothing here Dex has that you don't).
  > - **Backup and restore** — Dex now has two things you appear not to
  >   have: `backup-restore` and `dex-vault-backup`, both **new since your
  >   version**. What they would add: today your backups are written but
  >   nothing proves one can come back; these rehearse a restore and
  >   verify it. A deeper dive here would tell you exactly which pieces
  >   are worth taking (about two minutes).
  > - **Career growth** — Dex has this area but three of five members are
  >   dormant in the current release; nothing worth taking today.
  > - **Proactive health — could not tell** (loud, priced): nothing in
  >   your files matched either component. If you don't have this, the
  >   improvement would be a system that notices its own breakage before
  >   you do; a focused look reads your scheduled jobs and takes about
  >   two minutes.
  > - … (all 14, one line each; nothing omitted, ever)
  >
  > One more thing, and it goes the other way: your `weekly-ledger` habit
  > appears in nothing Dex publishes (Verified: no signed identity or job
  > carries it). Hold that thought — it may be worth offering back.
  >
  > Six areas you already have, three are release gaps, two are grey.
  > Pick the ones worth a real look — I'll go deep only there, and inside
  > any area you pick I'll assess every capability in it, one by one.

- **2:00** — Sam picks *backup and restore*, *proactive health*, and
  *durable work memory*. The engine mints a focus receipt for exactly those
  three families.
- **2:00–8:00** — Three family-scoped specialist packets plus the sceptical
  reconciler run, each carrying only its family's member ids, observations
  and evidence. **Every member of each selected family gets its own
  verdict** — for backup-and-restore that is all four capabilities, one by
  one: "`backup-now`: you have it, but your copy predates the
  restore-rehearsal step Dex added in v1.93 — here is the quoted diff and
  what the rehearsal would give you. `backup-restore`: Dex has it, you
  appear not to; it is the piece that proves a backup can come back.
  `backup-setup`: you have it, current. `dex-vault-backup`: Dex has it,
  you appear not to; it removes the remembering." No member is skipped or
  silently sampled.
- **9:00** — Report and close. Headline: "You are seven releases behind, and
  the gap is concentrated in three of fourteen areas; here is what Dex has
  in each that you appear not to, what each would improve, the two worth
  taking first, and the eleven areas where your older Dex is still doing
  exactly what current Dex does." Before the close, one question: the
  `weekly-ledger` idea from the map — "would you like to offer that idea
  back to Dave at Dex? The idea only, in words you approve first."

**What is different for A:** version distance leads. The family deltas
(`build_family_delta`) are pass-1 facts, not pass-2 judgements, because they
are derived from the signed `since_release` fields plus one Verified local
release observation.

### Persona B — a heavily customised Dex variant (drift, real strengths, contradictions)

*Priya started from Dex a year ago and has rewritten half of it: 41 authored
skills, 9 renamed, 3 Dex skills deliberately gutted, two MCP servers of her
own.*

- **0:00–1:30** — Same opening. The map looks different:

  > Your system started as Dex but has moved a long way — 62 of your 118
  > distinct items match no signed Dex identity (Verified: identity
  > matching, not judgement). Of the 14 Dex areas: five **you have**, four
  > where **Dex has pieces you appear not to** (each named, with what it
  > would add), three **could not tell from names alone** — for a system
  > this customised that usually means you built your own version, which
  > is exactly what a deeper dive can establish, and where you'd learn
  > whether Dex's version has anything yours doesn't. And going the other
  > way: eleven of your authored items serve jobs nothing in Dex's
  > catalogue covers — those are yours alone, and worth holding onto.
  > Housekeeping (also checked already): two skills exist in three drifted
  > copies each, and your top instruction file bans a tool that four
  > skills still call by name — both sides quoted below.

- **2:00** — Priya picks the three grey families plus *the contradiction*.
  Note what she is steering: for B, "grey" mostly means *the deterministic
  layer cannot see method equivalence*, which is precisely the question the
  specialists exist to answer.
- **2:00–9:00** — Family-scoped dives read her actual skills in full,
  cover every member of each selected family one by one, and score both
  sides on the six-check rubric. The verdicts speak in the offer voice:
  "Dex's `process-meetings` has a verification step yours appears not to —
  here is the quoted step and what silently fails without it" — never "you
  scored 3 of 6". The authorship axis (change 5, below) means her
  strengths section can only cite observations the engine marked as
  *authored*, never stock Dex files — so when the report says "your
  meeting pipeline closes a loop Dex's does not; Dex should learn the
  write-back-and-verify step", that sentence is structurally incapable of
  being Lens praising its own vendor's files.
- **10:00** — Report: two genuine strengths with quotes, one borrowing,
  the contradiction with both sides quoted, and the drifted copies priced
  in disk and confusion. Then the second reciprocal moment: the unique
  items called out in pass 1, now sharpened by what pass 2 actually read —
  "your write-back-and-verify step is genuinely not in Dex; want to offer
  the idea back to Dave? Idea only, your exact words, approved by you
  before anything is previewed, and a preview is not a send."

**What is different for B:** the mirror findings (drift, contradictions,
dead copies) are pass-1 deliverables because they are deterministic, and the
strengths/reciprocal story is the *centre* of pass 2 rather than an
afterthought. The authorship split is what makes praise trustworthy.

### Persona C — not Dex at all: a homegrown "G Brain" vault

*Gene never installed Dex. Their vault is 240 distinct capabilities of their
own design. No capability id will ever match; every family would sit at
UNRESOLVED forever if identity were the only axis.*

- **0:00–1:30** — The map opens with the honest frame, stated before any
  row, because for C the frame *is* the finding:

  > Nothing ties your system to Dex — no shared names, no release lineage
  > (Verified: zero identity matches across 240 items). So there is no
  > version to diff and no "behind". The honest comparison is by **job**:
  > here are the eight jobs Dex organises itself around, and what your
  > system visibly does about each — from your own files, not from
  > matching names:
  >
  > - **Start each day focused — you do this** (Supported: `morning-brief`
  >   runs on a schedule and writes a plan; quoted below)
  > - **Track people and relationships — partially** (Supported: person
  >   pages exist and are written to; nothing watches for gone-quiet)
  > - **Track people and relationships — partially**: Dex has something
  >   here you appear not to — an always-on radar that notices a
  >   relationship going quiet. What it would add to *your* person pages:
  >   the noticing, without you remembering to look.
  > - **Evolve the system itself — could not tell** (loud, priced: I
  >   found no health check, backup proof, or self-repair path, but
  >   absence of evidence is not evidence of absence — a two-minute
  >   focused look would settle it; if it really is missing, this is the
  >   area where borrowing would change the most)
  > - … (all 8 jobs, each with a citation or an honest Unknown)
  >
  > And the reverse: your commonplace-book pipeline — capture, distil,
  > resurface on a schedule — serves a job Dex doesn't publish at all.
  > That is yours; remember it when I ask about sharing ideas back.

- **2:00** — Gene picks two jobs. Pass 2 for C runs *job-coverage* dives:
  the specialist's question is not "which Dex capability matches" but "what
  does this system do about this job, how well by the six checks, and which
  single Dex pattern — if any — is worth borrowing as a pattern, not a
  file."
- **9:00** — Report framed as a loan, never a delta: "Here is Dex's surface,
  here is what yours already does — often better shaped to your work — and
  here is the one borrowing that cleared the bar: the restore-rehearsal
  pattern, because nothing in your 240 items proves a backup can come
  back." Rejections are the proof of reading: "account planning: no
  accounts exist anywhere in your system." Then the second reciprocal
  moment: "your commonplace-book pipeline from the map, plus the
  scheduled-resurfacing method pass 2 read in full — would you like to
  offer either idea back to Dave at Dex? The idea only — never your files,
  never names or company data — in exact words you approve, previewed
  byte-for-byte before anything is sent."

**What is different for C:** pass 1 is rendered on the **job axis** (the 8
signed jobs), not the 14 family rows — the families still get their one
ledger row each (the equality gates are non-negotiable), but the *story*
told to the person is jobs, and every family row for C carries the same
one-line explanation: "no name overlap is expected for a system that is not
Dex; this row exists so nothing is silently skipped." Section 4 specifies
the mechanism.

---

## 2. The two-pass mechanism, mapped onto the existing engine

### What stays exactly as it is

- The consent flow: `prepare` reads nothing, approval is the receipt,
  `--additional-root` only for folders the person named. Untouched.
- Catalogue verification, the signed family contract, the equality gates
  (every signed id exactly once in ledger and appendix; every observation a
  disposition). Untouched — pass 1 *depends* on them.
- Evidence minting, packet digests, the two-attempt protocol, the sceptical
  reconciler as the locked last packet, `MAX_RECOMMENDATIONS`, the
  three-suggestion shortlist, the report checker, the run store, the close.
- The rule that the host narrates and the engine keeps the books. The
  family map is engine-minted and digest-bound like everything else; a
  chatty host can read it aloud but cannot author a row of it.

### Pass 1: the deterministic family map (a new run stage)

Insert one stage between `CATALOGUE_VERIFIED` and `CONFIRM_JOBS`:

```
CREATED → SCOPE_APPROVED → CAPTURED → CATALOGUE_VERIFIED
        → FAMILY_MAPPED          ← new
        → FOCUS_CONFIRMED        ← replaces/absorbs CONFIRM_JOBS
        → ANALYSIS_PLANNED → ANALYSIS_COMPLETED → COMPARED → … → CLOSED
```

`FAMILY_MAPPED` runs, in order, everything in today's
`UnknownUntilProposedComparer.compare()` that takes no proposals:

1. `build_workflow_graph(fingerprint)`
2. `assess_significant_families(catalogue, fingerprint)` — the exact-identity
   matcher over all 14 families and every component
3. `assess_wow_expectations(...)` — the six-state fold
4. `_version_distance(...)` / `build_family_delta(...)` — persona A's story
5. `build_automatic_candidates(...)` and
   `_with_deterministic_skill_copy_recommendation(...)` — the provisional
   shortlist seeds
6. Housekeeping and authorship classification (change 5 below)
7. For persona C: the job-coverage projection (section 4)

The output is one engine-minted, digest-bound artifact — the **FamilyMap** —
containing all 14 family rows (state, matched/unresolved components, evidence
references, version delta if established, and a **price**: the packet count
and identity-set size a focused dive on that family would cost). The map is
stored like any run artifact and, per the RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT
lesson, is **re-derived at compare time and refused on mismatch** — the
stored copy is an audit record, never an input.

Crucially, `compare()` keeps doing all of this again at close. Pass 1 is not
a second source of truth; it is the same derivation surfaced early. One
shared helper, two call sites, a test that the two derivations are
byte-identical for the same inputs.

### Pass 2: focused packets replace the nine-packet sweep

Today `build_work_queue()` issues nine packets (eight `NORMAL_ROLES` + the
sceptical reconciler), each carrying the **entire** identity universe — all
catalogue ids, all evidence ids, all observations (`work.py` enforces the
shared context in `_queue_references_are_valid`). That is why the run costs
26 minutes and why the host's attention smeared across 115 entries produced
21 shallow dispositions.

Changes:

- **New `AnalysisMode.FOCUSED`** alongside `GUIDED` and `INVENTORY_ONLY`.
  `GUIDED` remains for "just do everything" (and for CI evaluation runs);
  `FOCUSED` becomes the default the skill drives.
- **A `FocusReceipt`**, minted at `FOCUS_CONFIRMED`, binding the exact
  family ids (or, for persona C, job ids) the person selected, digest-bound
  to the run and the FamilyMap digest. The person's multi-select in chat is
  the approval; the receipt is the record. No receipt, no focused packets.
- **Family-scoped packets.** For each selected family, the queue derives the
  packet's identity slice deterministically from the signed contract:
  `capability_ids` = the family's members; `observation_ids` = observations
  whose kind/identity the family's assessment profile admits, plus every
  observation the map matched to the family; `evidence_ids` = the map row's
  evidence plus those observations' evidence. The slice is computed by the
  engine, not proposed by the host.
- **Roles become lenses per dive, not a fixed sweep.** Each selected family
  gets one primary packet whose role is chosen by a fixed table (e.g.
  `backup-and-restore-confidence` → AUTOMATIONS_AND_LIVE_STATE;
  `durable-work-memory` → OPERATING_RHYTHM_AND_MEMORY;
  `meeting-follow-through` → PEOPLE_AND_WORK_CONTINUITY). Two packets always
  run regardless of selection because they are cheap and cross-cutting:
  CONTRADICTIONS_AND_RELIABILITY (scoped to instruction files + selected
  families' skills) and STRENGTH_AND_RECIPROCAL (scoped to *authored*
  observations only). The sceptical reconciler stays last and locked.
- **Queue validator changes** (`work.py`): `FOCUSED` queues require packets'
  identity tuples to be subsets of the run's allowed set *and* to equal the
  engine-derived slice for their (family, role) pair — recomputed on load,
  refused on drift. The `NORMAL_ROLES`-exact-order rule applies only to
  `GUIDED`; `FOCUSED` order is `(family_id, role)` lexicographic, so the
  queue digest stays deterministic. The shared-context rule relaxes to:
  shared `run_id`, `fingerprint_digest`, `catalogue_digest`, limits — but
  per-packet identity slices.
- **Full coverage inside a selected family (fixed requirement 1).** A
  focused packet's question demands a per-member verdict for *every*
  member capability of its family, one by one against Dex Core. The engine
  enforces it where enforcement is real: a family packet's receipt is
  accepted as `completed` only when its proposal set gives every member id
  of that family a disposition — otherwise it is the typed `insufficient`
  refusal that burns the bounded attempt and triggers the retry, exactly
  like an out-of-slice citation today. A member the dive genuinely could
  not settle is lawful only as an explicit could-not-tell proposal with a
  reason and a price; and `close` refuses a focused run whose ledger holds
  a silent `not-assessed` row for any selected-family member. Sampling
  inside a chosen family is not a quality bar — it is structurally
  impossible.
- **Everything not selected stays `not-assessed` — loudly.** The ledger
  already carries a disposition for all 115 entries; the change is that the
  report's *headline*, not its appendix, says "94 entries in 9 areas were
  not examined because you chose 3 areas; a full sweep costs about N more
  minutes" (change 6). Could-not-tell remains possible, loud, and priced —
  outside the selection. Inside it, the previous bullet applies.
- **Two reciprocal moments (fixed requirement 3).** Pass 1's map carries a
  deterministic **unique-to-you** section: authored observations (change 5)
  that matched no signed identity, alias, tool, or provider *and* whose
  admitted jobs no signed capability serves — engine-computed, so the host
  cannot flatter by invention. After pass 2, the close sequence gains one
  step before sign-off: the engine's result names the unique items (from
  the map) plus any reciprocal lessons pass 2 established, and the host
  asks once whether to offer those ideas back to Dave at Dex. The existing
  share flow is unchanged and remains separate: idea only, drafted as a
  pattern card, previewed byte-for-byte, sent only on an explicit yes, the
  offer's fate recorded in "What you decided", a declined idea never
  re-offered. Two asks per run is the ceiling, and the second only happens
  when the first surfaced something real — most runs still have at most
  one.

### 2a. The offer voice, and how it stays honest (fixed requirement 2)

The reframe is real and it is right: an audit says "you scored 3 of 6 on
backups"; the offer voice says "Dex has a restore rehearsal you appear not
to have, and here is what silently fails without one." The second sentence
is more useful, kinder, and — done properly — *more* honest, because it
states exactly what was compared and in which direction. But an educational
voice is one bad sentence away from marketing, so the honesty standard
binds it mechanically, not aspirationally:

- **"Appears not to have" is the strongest absence phrasing the voice may
  use, and it carries its basis.** The engine's map row is the citation:
  "no observation in the approved snapshot matched this component
  (Verified: identity matching over N observations)". "You do not have X"
  stays banned — SKILL.md's rule against unestablished absence is
  unchanged, and for bounded captures the RISK-BOUNDED-CAPTURE-ABSENCE
  lesson applies: an unread remainder downgrades the phrasing to
  could-not-tell.
- **Every benefit sentence has two labelled halves.** What X *does* comes
  from Dex's own signed brief or value line and is labelled as such —
  "Reported by Dex's published brief", never presented as something Lens
  verified about Dex. What X *would improve for this person* must cite the
  observed gap in their system: "your `backup-now` writes backups
  (Verified, quoted) and nothing in the snapshot verifies a restore
  (search run and quoted) — the rehearsal is the missing half of the
  loop." A benefit sentence that cannot name the local evidence for the
  gap does not get written; the report checker refuses an improvement
  claim with no quotation or Unknown under it, the same rule that already
  governs scored findings.
- **Pass 1's softer version is priced curiosity, not a verdict.** "Here is
  how your system could improve if you took a deeper dive into this area"
  is lawful at family level precisely because it promises the *dive*, not
  the outcome: the map row's state, its evidence, and the dive's cost are
  the whole claim. A pass-1 row never asserts capability-level absence —
  that assertion is only mintable by a pass-2 per-member verdict.
- **The voice runs both directions or it is a sales channel.** The same
  sentence shape serves the reciprocal finding: "you have X, Dex appears
  not to, and here is what Dex's users lose without it." The unique-to-you
  callout is deterministic (engine-computed from authorship and job
  coverage), so the balancing direction cannot be quietly dropped on a
  thin run.
- **No forced enthusiasm.** "Nothing Dex has would materially improve this
  area" is a complete, renderable pass-2 verdict and the rejections
  section is still mandatory. The offer voice changes what a finding
  sounds like, never how many findings there must be.

Net: the audit-to-offer reframe costs nothing from the honesty standard
because every offer sentence decomposes into claims the engine already
knows how to bind — a Dex-side published fact, a local-side quoted
observation or loud Unknown, and a labelled direction between them. The
skill's language rules gain one table (the sentence shapes above); the
report checker gains one rule (improvement claims cite the local gap).

### File-by-file

- **`work.py`** — add `AnalysisMode.FOCUSED`; add the (family → role) table
  next to `_ROLE_QUESTIONS` with per-family question templates that stay
  closed strings (parameterised only by signed family id, so the
  question-substitution guard still holds); relax the shared-context
  validator as above; `build_work_queue(context, mode, focus=...)` takes the
  focus receipt and computes slices; a focused family packet's receipt is
  `completed` only when its proposals cover every member id (the
  per-member coverage check lives beside the proposal-limit check in
  `record`/`submit_work`, refusing with the typed retry). Packet identity
  math (`packet_id` binds content) is untouched — a focused packet is just
  a packet with a smaller lawful universe.
- **`defaults.py`** — extract steps 1–7 of `compare()`'s deterministic
  prelude into `build_family_map(fingerprint, envelope)`; the engine calls
  it at `FAMILY_MAPPED`; `compare()` calls the same function and refuses a
  stored map that differs. `_reciprocal_answer` and `dispositions_from_
  proposals` unchanged. Add the authorship classifier to the observation
  post-processing (change 5).
- **`expectations.py`** — two changes. First, the silent-hole bug: today
  `assess_wow_expectations` returns `()` when the catalogue has no signed
  families (line 86–87), which is exactly why the first real run "produced
  no release-gap story" *without saying so*. Replace the silent empty with
  a loud typed state: every one of the 14 rows rendered as
  `not-gated` with the one-sentence reason ("the verified catalogue carries
  no signed capability families; family coverage cannot be assessed against
  this catalogue"). Second, add `state` pricing: each row carries the
  focused-dive cost so the multi-select is an informed choice.
- **`wow_gate.py`** — grade the two passes separately: pass-1 completeness
  (all 14 rows present and either determinate-with-evidence or loudly
  priced Unknown/not-gated — an *unpriced* Unknown is a hard failure) and
  pass-2 depth (existing scoring, restricted to selected families). This
  keeps faith with RISK-WOW-GATE-SCORES-SHAPE: an all-Unknown map cannot
  pass pass-1 by shape alone because Unknown earns nothing, and the
  authenticity caveat in the module docstring still applies — the engine,
  not the grader, owns token minting.

---

## 3. Latency and token budget

**Today (measured, one real run):** ~26 minutes, 21/115 assessed, 1
recommendation. The cost structure: nine sequential packets, each obliging
the host to hold the full inventory digest, the full 115-entry catalogue,
and all prior context while answering one broad question — call it 60–120k
tokens of attention per packet, ~0.5–1M tokens total, with most of each
packet's context irrelevant to its question. The person watches a spinner
for the entire duration and steers nothing.

**Pass 1 target: ≤ 2 minutes wall clock, ≤ 10k model tokens.**
Everything in pass 1 is engine arithmetic — exact-identity matching of a few
hundred observations against 14 families is milliseconds; capture dominates
(the bounded snapshot took ~1–2 minutes on the reference vault and is
unchanged). The only model tokens are the host *narrating* the map the
engine already computed: one turn, a few thousand tokens. There is nothing
to hallucinate because there is nothing to generate — every line of the map
quotes an engine row.

**Pass 2 target: 5–8 minutes for a typical 3-family selection, ~100–150k
tokens.** Three primary packets + two cross-cutting + sceptical = six
packets, each carrying roughly 1/10th of today's identity universe (a
family averages 2–8 members against 115 entries). The queue already permits
normal packets in any order (`pending_packets` returns all incomplete
normal packets), so a capable host can interleave or parallelise the three
family dives; only the sceptical packet is serialised by the lock. Per
packet: ~15–25k tokens including reading the selected skills in full and
producing the mandatory per-member verdicts — a family averages 2–8
members, and full one-by-one coverage inside the selection is exactly what
the pass-2 budget buys. That is the part that *should* cost tokens, because
it is the part that produces quotes.

**Net:** first useful, complete, honest output at ~2 minutes instead of a
first-and-only output at 26; a typical full session under 10 minutes; token
cost down roughly 5–8x; and the tokens that remain are spent reading the
person's actual files instead of re-reading the catalogue nine times. A
person who wants the old behaviour still has it: selecting all 14 families
is `GUIDED` with better bookkeeping.

---

## 4. Persona C: the jobs-to-be-done comparison model

When zero observations match any signed identity (a threshold the engine
computes, not the host: no capability, alias, MCP-server, tool, or provider
match across the whole fingerprint), the run is classified **non-lineage**
and the map is *rendered* on the job axis. Mechanism:

1. **The signed jobs list is the frame.** The catalogue already carries
   `jobs` and every family carries `jobs_served`. The 8 jobs become the
   pass-1 rows for persona C. Family rows still exist in the ledger (the
   equality gates demand them) with the uniform honest reason: "no
   identity lineage; assessed by job instead."
2. **Pass-1 job evidence is deterministic but weaker, and labelled so.**
   The engine cannot match names, but it *can* say, from the fingerprint's
   typed observations: this system has N scheduled automations, M MCP
   servers with these safe provider types, hooks at these moments, a vault
   shaped like this, and a workflow graph with these edges. Each job row
   gets the observations whose *kind* is structurally relevant (the same
   closed profile-rules idea as `_PROFILE_RULES`, keyed by job instead of
   family): `start-each-day-focused` admits AUTOMATION observations;
   `evolve-the-system-itself` admits HEALTH_CHECK and RECOVERY_PROOF; and
   so on. A job row with admitted observations is at most **Supported**
   ("something of the right shape exists and runs"), never Verified for
   method — the label discipline does the honest work.
3. **Pass 2 introduces one new proposal kind: `JOB_COVERAGE`.** A
   specialist packet scoped to a selected job carries that job's admitted
   observations and the signed capabilities serving that job (for the
   borrow-side comparison). The proposal maps observation ids to a job id
   with a six-check verdict and quotes; the engine validates the job id
   against the signed jobs list and the observation ids against the
   fingerprint, exactly as it validates capability mappings today. No
   fuzzy name matching anywhere: the *person's files* plus the specialist's
   evidence-cited reading are the only bridge, and every claim carries its
   quote or is Unknown.
4. **The report frame is a loan, not a delta** — SKILL.md already mandates
   this ("do not manufacture a lineage"); the engine now *enforces* it:
   on a non-lineage run, `VersionDistance` is structurally absent,
   "behind"/"new since yours" phrasings have nothing to cite, and the
   report checker refuses a delta-framed "Since the last look" section
   claiming release distance.
5. **The reciprocal direction gets equal weight.** For C, "what Dex should
   learn from you" is statistically the most likely headline — a 240-item
   homegrown system exists because its builder solved problems their own
   way. The STRENGTH_AND_RECIPROCAL packet always runs, scoped to authored
   observations, which for C is everything.

What this model refuses to do: score a job Absent because no observation
was admitted (that is `could-not-tell`, loud and priced — absence needs the
search, quoted); treat observation *kind* relevance as method equivalence;
or let the host invent a job the signed list does not contain.

---

## 5. The ten highest-leverage changes, ranked

Each entry: **payoff → surface → red-first test** (the test is observed
failing on the unchanged tree before the change lands; a test never seen
red proves nothing — the completion goal's own words).

1. **Deterministic family map before any specialist work.**
   *Payoff:* complete, honest, 14-row thematic coverage at ~2 minutes
   instead of nothing until minute 26; the single biggest responsiveness
   win available, and it costs zero new inference.
   *Surface:* `run.py` (new `FAMILY_MAPPED` stage), `defaults.py`
   (extract `build_family_map` from `compare()`), `orchestrator.py`,
   `cli.py`/`mcp_server.py` (`diagnosis map`).
   *Red test:* on a fixture vault, assert a run with **zero** specialist
   receipts exposes all 14 family rows with evidence references via the
   shipped `status`/`map` surface — fails today because assessments exist
   only inside `compare()`, which is unreachable before analysis completes.

2. **Kill the silent hole in `expectations.py`.**
   *Payoff:* the exact failure the first real run had — "no release-gap
   story" with no sentence saying why — becomes structurally impossible;
   every family row always exists, in a loud state.
   *Surface:* `expectations.py` (replace `return ()` on missing signed
   families with 14 `not-gated` rows), `report.py` (render them),
   `wow_gate.py` (an *absent* expectation set on a family-free catalogue
   is a hard failure; a loud `not-gated` set is not).
   *Red test:* family-free catalogue fixture → assert the rendered report
   contains 14 rows each stating the not-gated reason — fails today with
   an empty expectations tuple and a silent report.

3. **Focus receipt + family-scoped packets (`AnalysisMode.FOCUSED`).**
   *Payoff:* the person steers; token cost drops 5–8x; specialist
   attention concentrates where it produces quotes instead of smearing
   across 115 entries producing 21 shallow rows.
   *Surface:* `work.py` (mode, slices, validator), `run.py`
   (`FOCUS_CONFIRMED` + receipt), `orchestrator.py`, the skill's Phase 5.
   *Red tests (two):* build a FOCUSED queue for 3 families; assert every
   packet's `capability_ids` equal the engine-derived slice and that a
   proposal citing an out-of-slice catalogue id is refused with a typed
   error. Then submit a family receipt whose proposals cover all members
   but one; assert it is refused as `insufficient` (the retry fires), and
   assert `close` refuses a focused run holding a silent `not-assessed`
   row inside a selected family. All fail today because only the
   all-identity GUIDED queue exists and close has no per-selection
   coverage rule.

4. **Not-assessed becomes loud and priced, and the close requires the
   coverage sentence.**
   *Payoff:* "94 of 115 not examined" can never again hide in an appendix;
   an honest could-not-tell stays possible but costs a visible sentence
   with a visible price, which is what keeps it rare.
   *Surface:* `report.py` (headline coverage block: counts, the families
   they sit in, the cost of a follow-up pass), `reports check` (refuse a
   report whose not-assessed count is nonzero and whose headline lacks
   the block; refuse an improvement claim with no local-gap quotation or
   Unknown under it — the section 2a voice rule), FamilyMap rows carry
   dive prices.
   *Red test:* render a ledger with 94 not-assessed entries; assert
   `reports check` refuses it without the coverage block — fails today
   because the check has no such rule and the run's own report passed.

5. **Authorship axis: stock, authored, harness-shipped.**
   *Payoff:* Lens can never again praise stock Dex skills as the person's
   standout strengths; persona B's genuine strengths become trustworthy
   because the flattering sentence is structurally incapable of being
   vendor self-praise. (SKILL.md rule 5 exists; today nothing enforces it.)
   *Surface:* `observations.py` (an `origin` field derived at discovery:
   exact signed-identity match at matching content/version → `dex-stock`;
   `anthropic-*`/vendored → `harness-shipped`; else `authored`),
   `specialists.py`/`defaults.py` (a STRENGTH/RECIPROCAL proposal citing
   only non-authored observations is refused, exactly as an unknown
   evidence id is), STRENGTH packets scoped to authored observations.
   The same axis powers the pass-1 **unique-to-you** callout (fixed
   requirement 3): authored observations matching no signed identity and
   serving no signed job are the engine-computed candidate list for both
   reciprocal moments.
   *Red tests (two):* fixture of a pure stock-Dex vault → assert a
   strength proposal citing stock observations is refused and the
   strengths section reads "nothing beyond stock Dex cleared the bar" —
   fails today: the proposal is accepted and rendered as praise. Fixture
   with two authored, job-uncovered items → assert the FamilyMap carries
   them in its unique-to-you section — fails today: no such section
   exists.

6. **Version-distance headline for persona A (unblock and surface).**
   *Payoff:* the release-gap story — the whole point for the largest
   persona — leads the map the moment the signed family contract lands,
   instead of being an appendix fact.
   *Surface:* FamilyMap rows carry `build_family_delta` output; `report.py`
   promotes "N releases behind, gap concentrated in families X, Y" to the
   headline when lineage is Verified; when lineage cannot be established
   the same slot says "distance Unknown, and here is what would establish
   it" — loud, priced.
   *Red test:* fixture with a `dex-core v1.89.0` release observation
   against a v1.97.6 catalogue with signed families → assert the map's
   headline names the per-family deltas; second fixture with no release
   observation → assert the loud Unknown sentence. Both fail today (the
   distance is computed but never surfaced before the final report, and
   only when families exist).

7. **`JOB_COVERAGE` proposals and the non-lineage frame for persona C.**
   *Payoff:* the honest product for people who never installed Dex — the
   growth market — instead of a wall of UNRESOLVED rows that reads as
   "your system is invisible to us."
   *Surface:* `specialists.py` (new closed proposal kind + validation
   against signed job ids), `significant_families.py` (non-lineage
   classification threshold), job-keyed profile rules, `report.py` (job-axis
   rendering + loan framing), `work.py` (job-scoped packets under FOCUSED).
   *Red test:* zero-identity-match fixture → assert the map renders 8 job
   rows each with admitted-kind evidence or a loud Unknown, and that a
   report claiming "behind Dex" is refused by `reports check` — fails
   today: the report renders family rows all UNRESOLVED and nothing
   prevents delta framing.

8. **Live progress that speaks in the person's units.**
   *Payoff:* even a 6-minute pass 2 feels attended when `status` says
   "backup dive done (2 findings), memory dive running, ~3 minutes left"
   — typed fields, engine-computed from receipts, never host-invented;
   26 silent minutes is how today's honest run still felt broken.
   *Surface:* `run.py`/`orchestrator.py` (typed progress on status:
   packets done/pending per family, elapsed, bounded estimate from
   observed per-packet duration), `cli.py`, the skill's narration rules.
   *Red test:* assert `status --json` on a half-complete FOCUSED run
   carries per-family completion and elapsed fields — fails today: status
   names only the stage and next action.

9. **Two-pass Wow Gate: completeness graded separately from depth.**
   *Payoff:* the gate measures what the product now promises — no silent
   holes at pass 1, evidence-bound depth at pass 2 — and an unpriced
   Unknown anywhere is a hard failure, which is the mechanical form of
   "could not tell must be loud, priced, and rare."
   *Surface:* `wow_gate.py` (pass-1 sub-score: 14/14 rows determinate or
   loudly priced; `unpriced-unknown` hard failure; `sampled-selection`
   hard failure when a selected family holds any silent not-assessed
   member — the gate's form of fixed requirement 1),
   `scripts/run_wow_gate.py`.
   *Red test:* a ledger whose expectations include one Unknown row with no
   price and no reason-rendered sentence → assert hard failure — fails
   today (Unknown scores zero but fails nothing).

10. **Selection memory: the focus receipt joins "What you decided".**
    *Payoff:* the next run opens with "last time you looked at backup and
    memory; the other eleven areas have never been examined — want one of
    those?" — the concierge relationship, made mechanical, and the
    never-examined remainder can never quietly become permanent. The same
    ledger records the fate of both reciprocal moments (offered, shared,
    declined, deferred), so the post-pass-2 share-back ask honours the
    once-per-idea-ever rule across runs instead of within one.
    *Surface:* `report.py` (decisions section records selected and
    explicitly-not-selected families, plus each share-back offer's fate),
    `reports --last` consumers, the skill's Phase 0/6 and the close
    sequence (the second ask is a generated close field, not host
    improvisation).
    *Red test:* save a report from a 3-family FOCUSED run, start a delta
    run → assert the engine's since-last input names the 11 never-examined
    families — fails today: decisions track only capability adoptions.

**Top-five dependency note:** 1 and 2 are pure inversions/bug-fixes and can
land immediately; 3 depends on 1; 4 and 5 are independent of all others.
Nothing in the list waits on the contract signing except the *content* of
6 — its Unknown branch lands now.

---

## 6. What I would not build, and why

- **A fuzzy/semantic name matcher to "fix" persona C.** Embedding
  similarity between `g-brain-daily` and `daily-plan` is not evidence; it
  is a plausible guess wearing evidence's clothes, and it would launder
  precisely the claims the engine exists to refuse. The job axis plus
  specialists reading real files is slower and honest. If a mapping is
  worth asserting, it is worth a quote.
- **A numeric health score or letter grade for the person's system.**
  "Your setup scores 74/100" is the single most requested and most
  corrosive feature possible here. Every number invented for it would
  violate "never invent a score", and RISK-WOW-GATE-SCORES-SHAPE already
  demonstrated inside our own walls how a number detaches from truth. The
  map's 14 labelled states are the score.
- **Streaming provisional verdicts during pass 2** ("looks like your
  backups are broken… actually no"). A verdict that can be walked back
  teaches the person to discount all verdicts. The map fills in with
  *completed* rows only; in-flight rows say "being examined".
- **A resident watcher daemon.** Phase 9's cron one-liner the person
  pastes themselves is the right ceiling. A Lens process that runs
  unattended on their machine breaks the product's psychological contract
  (read-only, invited, visible) for marginal convenience.
- **Auto-widening scope to raise coverage.** Low coverage because the
  person approved one folder is a *loud, priced fact*, not a problem for
  the engine to solve by asking for `~/` — RISK-BOUNDED-CAPTURE-ABSENCE
  is the scar tissue here. The map's Unknowns name the folder that would
  resolve them, and the person decides.
- **Per-entry deep dives across all 115 as a "thorough mode".** That is
  the 26-minute run with better marketing. Depth-everywhere is
  indistinguishable from depth-nowhere at fixed attention; the
  three-recommendation and three-family disciplines are the product.
- **A second checklist in the skill to orchestrate the two passes.** The
  non-negotiable stands: the engine grows the `FAMILY_MAPPED` and
  `FOCUS_CONFIRMED` stages and the skill keeps doing "the next action
  `status` names". Any host-side pass tracking is how conclusions get
  laundered past engine-minted evidence.
- **Host-supplied family or job definitions** ("my system's areas are…").
  The frame must be signed or the comparison is against a rubric the
  person (or a prompt-injected file) authored for themselves. Their
  *content* is theirs; the *axes* are Core's, verified.

## The one-sentence version

Run the arithmetic first and show all of it; spend the model only where the
person points, and there spend it on every capability, one by one; speak as
an offer with both halves evidenced, never as an audit; and make every
silence in the product either impossible or expensive.
