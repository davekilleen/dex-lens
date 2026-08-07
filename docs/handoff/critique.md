# Adversarial Review — Outward Dex Implementation Handoff Pack

Reviewed: `/home/dexdev/outward-dex-handoff/HANDOFF.md` against `sources/decisions.md`, `sources/gates.md`, `sources/machinery.md`, the live GitHub issues (#347 body + Fable critique comment re-fetched and diffed — sources are faithful), and dex-core `origin/main` @ `9b88dc78`.

Verdict: the pack is largely faithful — no requirement of migration, no resemblance/aggregate scoring, no raw-content upload, no default sharing, no unapproved read/write path was found. But it contains **2 high-severity findings** (self-authorization circularity; a fabricated "response decision"), **1 unresolved contradiction inherited from the sources** (Card attachments vs G4), and **8 further violations, omissions, or untestable criteria**. File-reference verification passed in full (see end).

---

## Part 1 — Violations of the #347 standing contract / handoff bar

### F1 (HIGH) — The pack self-authorizes implementation, contradicting #357's "reviewed handoff pack" bar and R7's own fail-closed rule

**Offending passages** (HANDOFF.md §1.3 and §1.1):

> "(The fourth #347 out-of-scope item — 'building the concierge during the Wayfinder effort' — is now discharged: Wayfinder is done and **building is exactly what this pack authorizes**.)"

> "The Wayfinder planning phase is complete; **this pack is the implementation handoff it called for**."

**Why it violates.** #357 (verbatim): "Implementation begins only after **one reviewed handoff pack** contains … the **observed pilot evidence**, unresolved risks, assumptions, and explicit non-goals." R7 (gates.md, fail-closed): "An incomplete pack does not constitute handoff: implementation work does not begin." This pack (a) has not been reviewed by anyone — D9 defers even the M4 gate-evidence reviewer decision; (b) cannot contain observed pilot evidence, fault-injection results, runnable fixtures, or tabletop-exercised runbooks, because no code exists. Read literally, the sources are circular (the pilot needs a product; the handoff pack needs the pilot), and the pack papers over the circularity by declaring itself the handoff instead of resolving it. The Fable critique's closing line — "No product implementation, deployment, publication, or Core adoption is implied by this planning record" — makes self-authorization untenable.

**Fix.** Add an explicit, recorded interpretation decision (on #347, by Dave) that splits the handoff bar into two stages, and state it in §1: (1) **this pack is the build-authorization pack** for M1–M6 at pilot scope, becoming effective only after Dave's recorded review sign-off against a content hash of this pack; (2) **the R7 completeness pack produced at M6** (containing observed pilot evidence, red-team results, runbooks, etc.) is the handoff bar for *expansion beyond the pilot and any real-user automated adaptation outside it* — matching the Fable header "Required before implementation handoff **or expansion**." Delete "building is exactly what this pack authorizes"; replace with "building is authorized by Dave's recorded sign-off on this pack (see D9/D10)."

### F2 (HIGH) — The "decisions made in response" to the Fable critique are asserted, not recorded anywhere

**Offending passage** (§1.4):

> "Per #357's handoff bar, this pack must (and does) carry the Fable critique plus the decisions taken in response; **the response decision is: all six gates and all seven R-items are accepted as binding acceptance criteria and are scheduled into milestones M1–M6 below.**"

**Why it violates.** #357 requires the pack to contain "the post-plan Fable critique **and the decisions made in response to it**." Verified against GitHub: the Fable critique (2026-08-06T17:31:05Z) is the **only** comment on #347, and every child issue closed before it. No decision in response exists on any issue. The pack invents a decision and attributes it to the planning record — a traceability violation in the very sentence that claims traceability ("Everything in this pack traces to a numbered issue resolution").

**Fix.** Either (a) Dave posts the acceptance decision as a comment on #347 (accepting G1–G6 and R1–R7 as binding, plus the F1 two-stage interpretation and the F3 resolution below), and the pack cites that comment's timestamp; or (b) the pack moves this to Section 6 as a blocking open decision ("D0 — Accept the Fable gates as binding; blocks M1") and stops claiming the decision was already taken. Option (a) is correct; (b) is the honest fallback.

---

## Part 2 — Fable gates and required-before-handoff items

### F3 (HIGH) — Unresolved contradiction: #354's raw-material attachment opt-in vs G4's schema rejection by construction

**Offending passages** (§M-G, two consecutive bullets):

> "raw prompts/files/conversations/histories/personal examples excluded by default (**separate explicit opt-in per attachment**); submission per use case."

> "**Closed schema rejecting by construction (G4)**: secrets, **raw personal examples**, unique filesystem paths, and third-party confidential material fail validation outright — no 'submit with warnings.'"

**Why it violates.** These cannot both hold: #354 permits raw personal examples as separately-consented attachments; the Fable gate 4 (verbatim: "The Card schema rejects secrets, raw personal examples, unique paths, and third-party confidential material **by construction**") forbids them in the Card schema outright. The Fable critique is the later hardening layer the pack declares binding, but the pack reproduces both rules side by side without resolving them — so M5's G4 acceptance test ("schema rejects … raw personal examples") would make the #354 opt-in path unimplementable, or the opt-in path would silently weaken G4.

**Fix.** Record the resolution explicitly (in the same #347 response comment as F2). Recommended resolution consistent with both sources: the **Card schema itself never carries raw personal examples** (G4 holds absolutely); the #354 opt-in survives only as a **separate attachment channel outside the Card schema**, with its own G2 inventory entries, its own disclosure-manifest section, its own immutable-version consent, and its own withdrawal propagation — or is dropped for the pilot entirely. State the chosen answer in §M-G and add the corresponding test to M5's acceptance criteria (a Card embedding raw material is rejected; an approved attachment travels only via the attachment channel and appears byte-exactly in the disclosure manifest).

### F4 — No egress test over the adaptation journey (G2 as written requires it; the pack never schedules it)

**Offending passage** (§5.2):

> "Run at M1 (adapter), M3 (full read-only journey, subsuming R3's zero-analytics assertion — asserted at both layers), M5 (contribution path…)."

**Why it violates.** gates.md G2 acceptance criterion (verbatim): "An automated default-path egress test, run against a **full Diagnose → Decide → Adapt journey** with no sharing approved…" The Adapt stages (7–8) first exist at M4, and M4's acceptance list contains no egress run; the vague header "G1, G2, G6 … are re-asserted against the adaptation-capable build" is not a scheduled test and contradicts §5.2's explicit M1/M3/M5-only schedule. An adaptation engine is a new component that touches user files — precisely where an egress regression would appear.

**Fix.** In §5.2 and M4's acceptance criteria, add: "M4: G2 default-path egress test re-run over the full stage 1–8 journey (one approved benign adaptation, no sharing approved): zero unapproved egress, canaries and derivations absent from the wire."

### F5 — "The six gates are proven at M6's red-team (R6)" misstates R6's scope

**Offending passage** (§M4 header):

> "For pilot sequencing, 'the six gates' are proven at M6's red-team (R6); M4's exit bar is G1+G2+G3+G6 green plus T1–T9 green."

**Why it violates.** gates.md R6 defines the red-team as "the full hostile fixture suites from **G1, G2, G3, G4, and R3** executed against synthetic systems." It does not and cannot "prove" G5 (a process-control gate: hash-locked plans) or G6 (a classifier gate proven in M2/M4 CI). As written, M4 asserts a proof event that the cited gate does not deliver — leaving no single criterion that requires **all six** gates green before the first real-user automated adaptation, which is the Fable critique's exact demand.

**Fix.** Replace the sentence with: "Real-user automated adaptation (pilot, M6) requires all six gates green in CI **on the exact pilot build** (G1–G4, G6 via their suites; G5 via locked-plan process control), plus R6's red-team re-execution of the G1–G4 + R3 hostile suites against synthetic systems. M4's exit bar is G1+G2+G3+G6 green plus T1–T9 green." Add "all six Fable gates green on the pilot build (release-blocking CI check)" to M6's acceptance criteria.

### F6 — M4 requires triggering "the incident runbook," which is not built until M6

**Offending passages:** §M4: "`Unverified`/`Recovery failed` halts the chain, blocks further automated changes in the session, and **triggers the incident runbook**." §M6 Build: "incident/hard-stop/withdrawal/key-rotation/support **runbooks**…" (Also gates.md T8: "triggers the hard-stop/incident runbook (R7)".)

**Why it violates.** A milestone acceptance criterion referencing an artifact that only exists two milestones later is untestable at M4 — either the M4 test is vacuous or the runbook silently exists unreviewed. G3's fail-closed ("incident procedure triggered") likewise lands at M4.

**Fix.** Move authoring of the **incident** and **hard-stop** runbooks into M4's build list (M6 keeps withdrawal, key-rotation, and support, and keeps the tabletop drills for all five). M4 acceptance gains: "the incident and hard-stop runbooks exist and the `Recovery failed` fixture verifiably triggers them."

### F7 — R2 states vs Evidence Level: the mapping between the two vocabularies is never defined

**Offending passages:** §M-B: "All downstream logic (display, adaptation eligibility, pilot analysis) **branches only on these states**" (the 11 R2 states) — while §M-D and every finding surface display **Evidence Level: Verified / Supported / Reported / Unknown**, and §3.2 item 2 warns the axes must not be conflated.

**Why it is an omission.** The pack (correctly) keeps health verdicts, R2 evidence states, and Evidence Level as distinct vocabularies, but nowhere specifies the deterministic mapping from R2 evidence states to the displayed Evidence Level (e.g. does `observed` ⇒ Verified? does `stale` cap at Supported? what Level does `conflicting` yield?). Without a normative mapping, "display branches only on R2 states" and "every finding shows an Evidence Level" cannot both be tested, and two implementations could disagree while both "passing."

**Fix.** Add to M-B (and M1 acceptance): "A machine-readable, total mapping from R2 evidence-state combinations to Evidence Level ships with the state vocabulary; property test: every reachable state combination maps to exactly one Level; `stale`/`conflicting`/`insufficient`/`blocked`/`absent`/`not assessed` never map to Verified." Note in §M-B that this mapping is part of the shared currency whose change re-opens G3/G5/T7/P1.

---

## Part 3 — The eight non-negotiable boundaries (research note)

### F8 — Boundary 1 truncated: the pack drops "No Doctor `--heal`, no DexDiff adoption, no model-exposed mutator"

**Offending passage** (§3.5 item 1):

> "Diagnosis is read-only at the operating-system capability level, not by convention."

versus the research note (machinery.md, verbatim): "Diagnosis is read-only at the operating-system capability level, not merely by convention. **No Doctor `--heal`, no DexDiff adoption, no model-exposed mutator.**"

**Why it matters.** The dropped clause is the operational half of the boundary, and it is the one an implementer is most likely to trip: the pack *mandates* reusing Doctor's grammar (M-A) and DexDiff's patterns (M-G/M-E) — the exact modules whose mutating paths (`--heal`, the diff-adopt direct-write path) the boundary forbids from the diagnosis side. §2.3's general "the diagnosis side never holds a write capability" is a design statement, not the concrete prohibition, and §3.2 item 4 only forbids inheriting DexDiff's adopter for *adaptation*, not its presence in diagnosis.

**Fix.** Restore the full sentence in §3.5 item 1 verbatim, and add to M1's G1 acceptance: "the diagnosis process's binary/toolset contains no mutating entry point (no heal, adopt, or model-exposed write tool); conformance suite asserts the model-facing surface exposes read/preview/status operations only (mirroring `core/mcp/customization_migration_server.py`'s read-only pattern)."

### F9 — Boundary 5 (local-first means useful offline) has no acceptance criterion anywhere — and collides with automatic catalog refresh

**Offending/missing passages.** §3.5 item 5 states the boundary ("Local-first means useful offline: diagnosis and private recommendations work without an account or contribution") but no milestone tests it — M5's #356 test covers *account-free*, not *offline*. Meanwhile §2.1 says "Capability Exchange **may refresh this knowledge automatically at startup or on a schedule**" — startup network traffic on the default path that (a) is not declared in any G2 inventory/approved-traffic set (D8 only covers model calls), (b) muddies the egress tests' "records all network traffic" assertion, and (c) is exactly the dependency that breaks offline usefulness if handled naively.

**Why it violates.** A binding boundary with no test is, by the pack's own standard ("The gates are the spec… a feature without its hostile fixture is unfinished"), unfinished. The catalog-refresh sentence creates default-path egress that the egress harness must either allowlist explicitly or see as a failure — the pack resolves neither.

**Fix.** (1) Add to M3 acceptance: "Offline test: with all network interfaces disabled, the full stage 1–6 journey plus private recommendations completes successfully (using last verified catalog or none, and saying so per R4)." (2) Add to §2.1 and the G2 inventory: "catalog refresh is the only default-path network traffic; its endpoint, request contents (no user data, no identifiers beyond version), and failure behavior are inventoried fields; the egress harness pins this as the sole approved flow and asserts request bodies carry no canary derivations; refresh failure or absence never degrades diagnosis." (3) Extend D8 to decide the catalog-refresh default (auto vs prompt-first) alongside the model-call posture.

---

## Part 4 — Internal contradictions / missing or untestable acceptance criteria

### F10 — "Half plus one" is not an exact threshold for odd cohort sizes

**Offending passages:** §M-H/P1: "at least half plus one of enrolled participants show meaningful improvement"; gates.md P1 fixtures use N=7 ("3 of 7 improve → not successful", "4 of 7 improve but one severe trust failure…").

**Why it is untestable.** For N=7, "at least half plus one" is 4.5 → is the bar 4 (majority, floor(N/2)+1) or 5 (literal ≥ half+1)? G5 demands "exact improvement threshold[s]" locked before data; the pilot's own top-level verdict threshold is ambiguous for the very cohort sizes (#350: 6–8) the pilot allows, and the P1 fixture "4 of 7 improve **but** one severe failure" only tests the trust floor, leaving the 4-vs-5 question undecided.

**Fix.** Pin the integer in the pack and in the G5 locked plan template: "success threshold is ⌈(N+1)/2⌉ + adjustment" — concretely state the chosen table (recommended: N=6→4, N=7→4, N=8→5, i.e. strict majority; or 6→4, 7→5, 8→5 if 'half plus one' is meant literally) and add a P1 fixture at exactly N=7 with 4 improved and zero trust failures asserting the chosen verdict.

### F11 (minor) — D2 misattributes a #348-research quote to #349

**Offending passage** (§6 D2): "#349 mandates a separate codebase but reuse of dex-core patterns **'as libraries/patterns after extracting a host-neutral core'** implies Python compatibility."

**Why.** The quoted phrase is from the #348 machinery research (machinery.md: "Reusable as libraries/patterns after extracting a host-neutral core"), not from #349's resolution, which says nothing about libraries or language. In a pack whose rule is "where this pack summarizes, the issue text wins," misattribution corrupts the traceability chain.

**Fix.** Reword: "#349 mandates a separate codebase; the #348 machinery research recommends reuse 'as libraries/patterns after extracting a host-neutral core', which implies Python compatibility if taken as libraries."

---

## Part 5 — File-reference verification (PASSED)

Checked against dex-core `origin/main` @ `9b88dc78d5347fd1b25f88c942a679d5b82dc465` (the exact commit the pack pins):

- All 13 cited files exist on origin/main: `core/lifecycle/service.py`, `core/transaction/engine.py`, `docs/dex-doctor-spec.md`, `core/customization_migration/{service,inventory,model}.py`, `core/mcp/customization_migration_server.py`, `docs/customization-migration-threat-model.md`, `.claude/skills/diff-generate/SKILL.md`, `.claude/skills/diff-adopt/SKILL.md`, `docs/architecture/DEX-CORE-MAP.md`, `CHANGELOG.md`, `core/portable_contract.py`. ✔
- Spot-checked line-range claims: `core/lifecycle/service.py` ~L646–704 does contain the preview/execute adoption surface (`build_and_preview_adoption` / `execute_approved_adoption`, approval token = preview sha256) ✔; `core/transaction/engine.py` L1–16 is the plan→authorize→snapshot→apply→verify→commit contract docstring ✔.
- Drift-audit claims confirmed live: `legacy-qmd-reconciliation` present in `update_write_verdict`'s operation whitelist (L426, L511–537), `System/.dex/health` generated rule (L261), narrowed bridge-only `vault-mcp-json` exception (L315–318) ✔ — supporting the pack's warning to read the live contract.
- Branches exist on origin: `research/capability-exchange-existing-machinery` @ `68dde1f9` (matches pack) with `docs/research/capability-exchange-existing-machinery.md` present on that branch (note: **branch-only, not on main** — the pack cites it correctly as a branch artifact); `codex/wayfinder-capability-exchange` with `CONTEXT.md` present ✔.
- Issue cross-check: #347 OPEN, its body's standing contract / not-yet-specified / out-of-scope lists match `sources/decisions.md` verbatim; the Fable critique comment (2026-08-06T17:31:05Z) matches verbatim and is the **only** comment on #347 (basis of F2). ✔

---

## Summary table

| # | Severity | Category | One-line |
| --- | --- | --- | --- |
| F1 | High | #357/R7 violation | Pack self-authorizes building; #357 requires a *reviewed* pack and R7's fail-closed forbids treating an incomplete pack as handoff; circularity unresolved |
| F2 | High | #357 violation / traceability | The "response decision" accepting gates as binding is asserted but recorded nowhere on GitHub |
| F3 | High | G4 vs #354 contradiction | Raw-example attachment opt-in coexists with schema rejection "by construction" — unresolved |
| F4 | Med | G2 omission | No egress test scheduled over the adaptation (stage 7–8) journey; G2 requires the full Diagnose→Decide→Adapt run |
| F5 | Med | Fable-gate wiring | "Six gates proven at M6 red-team" — R6 covers G1–G4+R3 only; no criterion requires all six green before real-user adaptation |
| F6 | Med | Milestone ordering | M4 acceptance triggers an incident runbook built only in M6 |
| F7 | Med | R2 omission | No defined mapping from the 11 R2 states to Evidence Level — dual-vocabulary display untestable |
| F8 | Med | Boundary 1 omission | Dropped "No Doctor `--heal`, no DexDiff adoption, no model-exposed mutator" while mandating Doctor/DexDiff reuse |
| F9 | Med | Boundary 5 omission + contradiction | Offline usefulness never tested; automatic catalog refresh creates undeclared default-path egress |
| F10 | Low | Untestable criterion | "Half plus one" ambiguous for N=7; G5 demands exact thresholds |
| F11 | Low | Traceability | D2 attributes a #348-research quote to #349 |

File references: **all verified present on origin/main** (plus two correctly-cited branch-only artifacts).
