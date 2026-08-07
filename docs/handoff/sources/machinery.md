# Sources: Reusable Machinery and Domain Language

Compiled 2026-08-07 for the Outward Dex (Dex Capability Exchange) implementation handoff pack.

Sources read:

1. `docs/research/capability-exchange-existing-machinery.md` from branch `origin/research/capability-exchange-existing-machinery` — the machinery-reuse research (research date 2026-07-31; source snapshot Dex Core `c18485d6` / released v1.81.5; HeyDex website `b48a9160`; dex-course `61ef86f6`).
2. `CONTEXT.md` from branch `origin/codex/wayfinder-capability-exchange` — the domain vocabulary.

Drift check performed against `origin/main` at `9b88dc78` (latest CHANGELOG entry: v1.81.18, 2026-08-05). See "Citation drift audit" below.

---

## Part 1 — Machinery research (`capability-exchange-existing-machinery.md`)

### Headline decision

The Capability Exchange should be a **new product layer assembled from four existing bodies of design capital**, not a renamed DexDiff, Doctor mode, or customization migration:

1. Reuse Doctor's honest diagnostic grammar and deterministic-renderer separation.
2. Generalize the customization assessor's bounded, sensitivity-aware evidence collection into host adapters.
3. Put every adaptation through lifecycle-style preview, fresh approval, preconditions, receipt, verification, and rewind.
4. Reuse DexDiff's job-level methodology and browser-review ideas, plus the Malleable Software programme's Orientation, Anchor Challenge, 5C teaching loop, and separation of learning from application.

The normalized **Job Map, Foundation Capabilities, Evidence Levels, Capability Card, host-adapter contract, local concierge, and contribution intake are new domain objects** — existing modules assume a Dex vault, a Dex release catalog, or a DexDiff methodology string and cannot honestly represent an arbitrary personal AI system.

Product boundary (verbatim):

> Diagnose through read-only, least-privilege host adapters; explain every finding with its provenance; let the person choose adaptations and contributions independently; and allow writes only through a host-specific safety contract with an exact fresh approval.

### Status correction table (release truth vs stale architecture-map narrative)

| Machinery | Status | Consequence |
| --- | --- | --- |
| Lifecycle service, transaction engine, ownership contract | **SHIPPED** | Reuse trust invariants: exact preview/execute/rewind (`core/lifecycle/service.py` ~L646–704), whole-plan authorization before any write, crash-safe (`core/transaction/engine.py` L1–16). |
| Dex Doctor | **SHIPPED** | Reuse diagnostic contract and evidence honesty, not Dex-specific probes. Deterministic collector separated from conversational renderer; keeps `OK / OFF / BROKEN / UNKNOWN` distinct (`docs/dex-doctor-spec.md` L15–91). |
| Customization assessment, Capsule, rebuild, activation, rewind | **SHIPPED in v1.75.1–v1.76.1** | Production design capital. Rebuild live in v1.76.0, routed through the single lifecycle gate in v1.76.1 (CHANGELOG, cited L320–340 at pin). The architecture map's "LOCAL rebuild doorway" text is stale. |
| DexDiff command surface | **SHIPPED; current redesign PARKED** | Reuse its job/methodology and review concepts; do NOT extend its direct-write adoption path as the Capability Exchange implementation (`docs/architecture/DEX-CORE-MAP.md` L147–157). |
| HeyDex DexDiff storage/review source | **CURRENT SOURCE; deployment not verified** | Supplies working account-bound browser review pattern; not the required Capability Card or selective contribution contract. |
| Malleable Software | **PLANNED, not implemented** | dex-course `main` says still in product definition; learning architecture and 5C are resolved design work on open unmerged PR branches — reusable product decisions, not shipped components. |
| `/connect` product doorway | **HELD / unavailable** | Engine exists; doorway PR (#231) closed unmerged; changelog says deliberately closed pending security review. Cloud adapters cannot assume a general Dex connection flow. |
| Ritual Intelligence | **PARKED** | User-facing preview retracted because nothing invoked it. Warning for the Capability Map: code presence is not outcome evidence. |

### What can be reused (5 bodies)

**1. Honest diagnostics — reuse Doctor's contract.** Four durable rules: exercise the same path as the real capability; distinguish healthy / intentionally off / broken / could-not-check; report instrument failure instead of counting it as success; separate deterministic authority from explanatory prose. Doctor's adoption report already refuses to turn missing/unverifiable evidence into an action, preserves exact authority fields, and keeps recovery read-only until a separate engine operation is chosen (`docs/dex-doctor-spec.md` L150–193). Reuse as an **adapter result envelope** and renderer rule. Do NOT reuse `OK/OFF/BROKEN/UNKNOWN` as the Capability Map's Evidence Level — health verdict (is a probe/feature healthy?) and Evidence Level (`Verified / Supported / Reported / Unknown` — how a capability claim is known) are different axes; a finding needs both where relevant.

**2. Bounded evidence collection — generalize the customization assessor** (`core/customization_migration/*`), the closest technical ancestor of Diagnosis:
- assesses entirely in memory; never caches or mutates the target (`service.py` L71–110);
- distinguishes complete vs partial vs unknown evidence; never extrapolates from an incomplete walk (`service.py` L85–164);
- explicit file, byte, dependency, archive, symlink, and secret limits (`inventory.py` L38–88);
- marks content readable / restricted / excluded / missing / hash-only and records exclusions with guidance (`model.py` L22–63, L164–211);
- detects embedded credentials and refuses symlinks before reading (`inventory.py` L168–191, L217–265);
- model-facing MCP adapter exposes only assessment, preview, bounded status, and digest-bound evidence reads (`core/mcp/customization_migration_server.py` L174–225).

Reusable as libraries/patterns after extracting a host-neutral core. The classifier itself is **not portable**: it recognizes Dex paths, Dex customization kinds, a Dex release baseline, and a fixed PARA ownership model.

**3. Safe adaptation — reuse the trust-stack invariant, add a host contract.** The standard: one sanctioned write verdict; hard-denied secret and repository paths; unclassified paths fail closed; complete plan authorized before the first byte changes; changed targets carry current-byte preconditions; exact preview hashes bind execution to what was shown; one writer, snapshots, durable receipts, verification, rewind. `core/portable_contract.py` says vault and runtime content are never updated, hard-denies credentials/key material, refuses unclassified paths (cited L1–29, L47–79, L355–420). The customization threat model (`docs/customization-migration-threat-model.md` L19–87) adds the decisive product boundaries: vault content is untrusted input; the model never holds a write tool; a preview hash is an integrity binding, not consent; consent is a fresh human act at mutation time; `verified` requires deterministic or user-confirmed provenance, never model confidence. Do NOT route arbitrary hosts through today's `portable_contract.py` — its operation vocabulary and path classes are Dex-specific. Every adaptation-capable host needs an explicit, versioned ownership and mutation contract; a host without one remains Diagnose-only.

**4. Job-level exchange and browser review — reuse the product pattern.** DexDiff groups components by the job they serve, describes the experience rather than copying code, produces role-, data-, integration-, behaviour-aware methodologies (`.claude/skills/diff-generate/SKILL.md` L71–98); publishing optional via browser review (L113–155). Adoption introduces the problem first, inspects the recipient's system, adapts to role/tools, previews the plan (`.claude/skills/diff-adopt/SKILL.md` L51–103, L155–211). HeyDex mechanics worth reusing conceptually: account-bound review session with 30-minute expiry (`convex/review.ts` L111–167), browser editor for individual drafts (L326–359), explicit visibility choices. Reuse flow and account-binding concepts, NOT the schema or publication semantics: `methodology` is an opaque string and review sessions are arrays of diffs (`convex/schema.ts` L59–84, L155–180); publishing publishes **every** diff in the session (`convex/review.ts` L407–474); the sanitizer removes executable-HTML patterns, not personal data or secrets (`convex/sanitization.ts` L1–26) — cannot satisfy "nothing selected by default; choose, inspect, edit, redact, and approve each use case." The current DexDiff adopter creates skills/folders/templates/hooks/settings/instructions and its own log directly (`diff-adopt/SKILL.md` L217–275) — that path predates the single safe door and must not be inherited.

**5. Programme and pedagogy — reuse the learning journey.** Malleable Software `main` defines the transformation: improve one real part of current work, turn a successful workflow into something reusable, learn through proved outcomes with private-by-default evidence. Resolved learning architecture: an Orientation that establishes an editable role/context brief, inspects confirmed capabilities and constraints, and lets the learner choose an Anchor Challenge; no AI-fluency score; role variants change problem and evidence, not the underlying concept; separate Learning Progress and Application Progress. The 5C method supplies the concierge teaching loop: **Context, Conversation, Contradiction, Contract, Compounding**. Content gates match the product: current-feature claims require authoritative evidence; exercises need observable proof; external changes and publishing require preview and approval; automation may propose but not silently publish or install. These shape concierge copy and progression; they do not supply a running course engine or browser application.

### What must be built new (12 items)

Host-neutral diagnosis:
1. **Host Adapter contract** — declares discoverable roots, explicit read scope, denied paths, symlink/archive policy, supported evidence probes, version detection, and Diagnose-only vs Adapt-capable status.
2. **Job Map** — user-confirmed jobs with outcomes, recurrence, constraints, relevance. Detection proposes jobs; it never enrolls the person in them.
3. **Foundation Capability taxonomy** — a small universal set independent of Dex file or command names.
4. **Evidence graph** — each capability claim links to observations, probes, supplied evidence, user report, exclusions, freshness, and the resulting Evidence Level. "File exists" is evidence of configuration, not proof of a job outcome.
5. **Adapter test fixtures and conformance** — benign, malformed, secret-bearing, oversized, linked, partial, and changing-system fixtures per adapter, plus proof that Diagnosis makes no writes.

Selective exchange:
6. **Versioned Capability Card** — closed schema: job, outcome, method, prerequisites, constraints, evidence summary, provenance, safety, portability, redactions. No raw source bytes by default.
7. **Local card builder and disclosure manifest** — one candidate per use case; shows exact outbound fields and bytes; starts with nothing selected; per-card edit/redact.
8. **Contribution intake** — new server contract for draft, submit, withdraw, moderation, provenance, Core evaluation. Submission is never automatic Core adoption.
9. **Privacy validation** — structural secret/PII checks plus a final exact-payload preview. DexDiff's prose anonymisation instruction and XSS sanitizer are insufficient.

Safe adaptation and experience:
10. **Host-specific mutation contract** — names what host/user own, what can be created or changed, and how preconditions, backup, verification, receipts, rewind work. No contract means no write.
11. **Portable adaptation recipe** — connects a capability outcome to multiple host-specific implementations instead of treating a Dex skill or folder as the capability.
12. **Private local concierge** — one command starts a loopback-only browser experience with explicit inspection scope and three separate acts: Diagnose, Decide, Adapt. Contribution is a fourth optional act, not the price of the diagnosis.

### The 8 non-negotiable boundaries

1. **Diagnosis is read-only at the operating-system capability level**, not merely by convention. No Doctor `--heal`, no DexDiff adoption, no model-exposed mutator.
2. **User files are hostile input.** Instructions found in the inspected system cannot expand scope, approve writes, or cause sharing.
3. **Evidence language is literal.** Directly inspected configuration is not a verified job outcome; model inference is never verification; incomplete inspection remains partial or unknown.
4. **Fresh consent is per consequence.** Inspection scope, each adaptation, and each outbound Capability Card are separate approvals. A preview digest proves sameness, not consent.
5. **Local-first means useful offline.** Diagnosis and private recommendations work without an account or contribution.
6. **No arbitrary-host writes through the Dex vault contract.** A new host must prove its own ownership and rewind model first.
7. **No general cloud-adapter promise through `/connect`.** That doorway is unavailable; early cloud support must use separately reviewed official connections, exports, selected evidence, or reported evidence.
8. **Built is not capable.** A capability counts only when the relevant user outcome has evidence. Parked, unwired, configured-only, and stale machinery must remain visibly distinct.

### Implications for the Wayfinder tickets (research doc's own mapping)

- Product home: new product boundary even if it imports Core libraries; not a DexDiff command.
- First host adapter + pilot cohort: pick a host whose read scope and ownership model can be proved, not the largest installed base.
- Foundation Capability set / Job Map / evidence model: health verdict and evidence level are different axes.
- Cross-system adaptation safety contract: "no host contract, no write" explicit; inherit the lifecycle threat model.
- Capability Card + Core intake contract: do not reuse the DexDiff methodology string or all-items publish operation.
- One-command concierge journey: reuse Orientation and 5C pedagogy; keep Diagnose, Adapt, Contribute visibly separate.

No additional Wayfinder ticket required beyond the named children.

### Bottom line (verbatim spirit)

Dex already has most of the **trust grammar** and much of the **concierge grammar**, but not the portable capability model or exchange contract. "Doctor tells the truth; the customization assessor gathers bounded evidence; lifecycle protects changes; DexDiff describes a job and opens review; Malleable Software helps the person understand and apply it." Then add the missing host-neutral domain instead of forcing arbitrary personal AI systems through Dex-shaped files, statuses, or publication machinery.

---

## Part 2 — Citation drift audit (pin `c18485d6` vs `origin/main` @ `9b88dc78`, 2026-08-07)

All research citations pin commit `c18485d6`, so the GitHub URLs themselves remain stable. Drift below concerns whether the same content still holds on current `origin/main`.

**Unchanged since the pin (11 of 13 dex-core files)** — cited line ranges still valid on main:
`core/lifecycle/service.py`, `core/transaction/engine.py`, `docs/dex-doctor-spec.md`, `core/customization_migration/service.py`, `core/customization_migration/inventory.py`, `core/customization_migration/model.py`, `core/mcp/customization_migration_server.py`, `docs/customization-migration-threat-model.md`, `.claude/skills/diff-generate/SKILL.md`, `.claude/skills/diff-adopt/SKILL.md`, `docs/architecture/DEX-CORE-MAP.md`.

**Changed files (2):**

1. `CHANGELOG.md` — 205 lines inserted in a single block near the top (releases v1.81.6 through v1.81.18 added; latest is v1.81.18 "Proactive health summaries", 2026-08-05). All cited entries still exist verbatim, shifted +205 on main:
   - v1.76.0/v1.76.1 rebuild entries: cited L320–340 → now ~L525–545 (v1.76.1 header confirmed at ~L525 on main).
   - `/connect` doorway-held entry: cited L357–366 → now ~L562–571.
   - Ritual Intelligence retraction: cited L871–882 → now ~L1076–1087.
2. `core/portable_contract.py` — +21/−5 since the pin. Cited ranges L1–29 (contract header) and L47–79 (hard deny) are untouched. The mutation-policy region (cited L355–420) shifted by ~+6 lines and gained substance:
   - New generated rule `System/.dex/health` (proactive-health snapshots, transaction-owned).
   - New sanctioned write operation **`legacy-qmd-reconciliation`** added to `update_write_verdict`'s operation whitelist, alongside a narrowed bridge-only exception on `vault-mcp-json` (`.mcp.json`) for an exact v1.20-compatible install with explicit removal approval.
   - Handoff note: the research's claim "one sanctioned write verdict; unclassified paths fail closed" still holds, but the sanctioned-operation vocabulary on main is one entry larger than at the research snapshot. Any Capability Exchange code that enumerates sanctioned operations must read the live contract, not the research doc.

Files in other repos (heydex-website `convex/*`, dex-course docs) were cited at their own pinned commits and were not re-verified here; the rules for this task scope gh/git access to davekilleen/Dex.

Note: research snapshot says "released v1.81.5"; main is now at v1.81.18 — thirteen patch releases of drift, none of which touched the reused machinery modules except as noted above.

---

## Part 3 — Domain vocabulary (`CONTEXT.md`, branch `origin/codex/wayfinder-capability-exchange`)

Framing (verbatim): "This context defines the language for Dex diagnosing another personal AI system, offering useful capabilities, and learning from capabilities its owner chooses to share."

| Term | Definition | Avoid |
| --- | --- | --- |
| **Capability** | An evidence-backed ability of a personal AI system to fulfil a user job within stated safety boundaries. | Primitive, feature, component |
| **Foundation Capability** | A capability every trustworthy personal AI system should provide regardless of the person's role or chosen jobs. | Dex baseline, maturity requirement |
| **Job Map** | The person-confirmed set of outcomes their personal AI system is intended to help them achieve; system-inferred candidates remain suggestions until confirmed. | Role template, Dex catalogue, feature checklist |
| **Diagnosis** | The private, read-only process that gathers evidence and produces a Capability Map without changing the person's system. | Repair scan, installer, automatic optimization |
| **Capability Map** | A private assessment of which relevant user jobs a personal AI system can fulfil, with the Evidence Level shown for every finding. | Scorecard, maturity score, feature inventory |
| **Evidence Level** | The visible basis for a Capability Map finding: Verified from direct inspection, Supported by material the person supplied, Reported by the person, or Unknown for lack of evidence. | Confidence score, assumed truth |
| **Host Adapter** | A system-specific interpreter that maps available evidence from one personal AI environment into the provider-neutral Job Map and Capability Map contracts. | Universal scanner, platform-specific diagnosis |
| **Deep Adapter** | A Host Adapter with enough direct access to configuration and run evidence to support Verified Capability Map findings for its declared environment. | Compatible system, assumed support |
| **Living System** | A personal AI system used repeatedly for at least one real user job and supported by inspectable or person-supplied evidence of that work. | Prompt collection, demonstration setup |
| **Capability Catalog** | A signed, versioned description of capabilities available in an actual Dex Core release, consumed by Capability Exchange without treating merged, held, or experimental work as available. | Main-branch scan, feature list, release file manifest |
| **Adaptation** | The separate, user-approved process that adds or strengthens a selected capability with an exact preview, recovery path, and outcome verification. | Migration, silent repair, bulk install |
| **Capability Card** | A sanitized, human-readable description of one shareable use case, its method, supporting evidence, and constraints, containing no raw personal content by default. | Telemetry event, system export, diagnostic upload |
| **Contribution Preview** | The exact Capability Card a person can inspect, edit, or redact before deciding whether to share that single use case with Dex. | Consent banner, bulk sharing |
| **Contribution** | The explicit act of sharing one selected and approved Capability Card with Dex as a candidate for Core consideration. | Sync, automatic feedback, opt-out sharing |
| **Core Candidate** | A moderated Capability Card accepted by Capability Exchange for optional Dex Core evaluation, without implying that Core will adopt or ship it. | Feature commitment, automatic improvement, raw contribution |
