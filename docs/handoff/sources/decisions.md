# Outward Dex (Dex Capability Exchange) — Complete Decision Inventory

Extracted verbatim from GitHub issues davekilleen/Dex #347–#357 on 2026-08-07.
#347 is the open parent Wayfinder map; #348–#357 are closed children, each resolved by a "## Resolution" (or equivalent) comment. Resolutions are reproduced verbatim; normative language is preserved.

---

## #347 — Wayfinder: Dex Capability Exchange [OPEN — parent map]

### Destination statement (verbatim)

> Reach a decision-complete product definition for a host-system-first Dex concierge that privately diagnoses a living personal AI system at the user-job level, helps its owner selectively adapt evidence-backed Dex capabilities without migrating to Dex, and lets them explicitly contribute chosen, previewable Capability Cards back to Dex.

Notes on scope (verbatim): "Planning only: the map ends when the product route is clear enough to hand off for implementation. Use grilling and domain-modeling for decisions, prototype for experience questions, and research for facts outside this repository."

### Standing product contract agreed with Dave (verbatim)

- The person keeps and improves their existing system; Dex installation or migration is never required.
- A Capability is a portable, evidence-backed ability to fulfil a user job, not a Dex component.
- Diagnosis combines universal Foundation Capabilities with a user-confirmed Job Map.
- Every finding exposes separate Capability State, Evidence Level, and Safety Boundary axes.
- Diagnosis is private and read-only; Adaptation is separate, selective, previewed, reversible, and explicitly approved.
- The first deep adapter is local/file-based, but the product is local-first rather than local-only.
- One trusted command opens a private local browser concierge.
- The first user has a living personal AI system: at least one repeated real job with some supporting evidence, regardless of technical ability.
- Sharing back is optional per use case. Nothing is selected by default; the person inspects, edits, redacts, and approves each Capability Card separately.

### Not yet specified (verbatim)

- How cloud-only host systems evolve from guided or export-assisted diagnosis into deeper adapters.
- How Capability Cards are versioned, updated, withdrawn, attributed, and potentially rewarded once contribution volume exists.
- Whether a broader community or team exchange emerges beyond the first Core-learning loop.
- How the programme relates long-term to DexDiff, the Malleable Software programme, and any future hosted Dex experience after its initial product home is chosen.

### Out of scope (verbatim)

- Building or shipping the concierge during this Wayfinder effort.
- Requiring migration to Dex or scoring systems by resemblance to Dex.
- Uploading raw system contents, prompts, histories, or personal data as the price of diagnosis.
- Automatically adopting contributed capabilities into Dex Core.

### Fable critique comment (davekilleen, 2026-08-06T17:31:05Z) — FULL VERBATIM

> ## Fable critique and hardened plan
>
> Fable reviewed the complete Wayfinder definition after #357. The core product direction remains sound and should not be weakened: host-system-first ownership, private read-only diagnosis, confirmed Success Contracts, separate capability/evidence/safety axes, Diagnose → Decide → Adapt, version-bound Card consent, separate Core adoption, pseudonymous provenance, honest withdrawal, and outcome-plus-trust pilot measurement.
>
> ### Non-negotiable gates before any real-user automated adaptation
>
> 1. **Constrained adapter containment.** The Claude Code deep adapter is an evidence collector, not an agent: no arbitrary shell, hooks, writes, or network egress; approved real-path allowlist; immutable inspection snapshot; explicit symlink, mount, ignored-file, credential, and secret handling; prompt-injected files treated as untrusted data; separate consent for any external model request. Hostile fixtures must prove no scope escape. If this cannot be proven, the pilot uses guided/export-assisted evidence.
> 2. **Field-level data boundary.** Define collection, derivation, display, storage, sharing, deletion, and audit for every field, including summaries, embeddings, hashes, excerpts, receipts, browser storage, crash logs, and telemetry. Default processing is ephemeral and telemetry-free; a default-path egress test proves no unapproved raw or derived representation leaves the machine.
> 3. **Adaptation allowlist and recovery.** Automated changes are limited to explicitly allowed, reversible local operations. Messaging, publishing, purchasing, deletion or overwrite of source data, credentials or permissions, security weakening, external-system changes, and other high-impact actions are blocked or manual-only. Every allowed change has preconditions, backup/transaction boundary, idempotency, and crash recovery. Fault injection must restore the exact pre-change state; uncertainty yields `Unverified` or `Recovery failed` and blocks continuation.
> 4. **Card permission and withdrawal state machine.** Separate review, storage, moderation, attribution, reuse, and distribution permissions; define propagation across Exchange Cards, caches, exports, and Core releases. Submit → review → reject → withdraw tests must prove no new use after withdrawal. The Card schema rejects secrets, raw personal examples, unique paths, and third-party confidential material by construction.
> 5. **Predeclared pilot measurement.** For every Success Contract, set the baseline window, follow-up window, exact improvement threshold, objective or contemporaneous measure where feasible, missing-data/dropout treatment, and definitions of regression, near miss, and severe failure before seeing results. The denominator is all enrolled participants; missing evidence is not success. The pilot remains formative and cannot claim general safety.
> 6. **High-impact job taxonomy.** Jobs involving sending messages, money, permissions, deletion, credentials, health, legal, financial decisions, or third-party confidential data may be diagnosed but cannot trigger automated adaptation. They fail closed to a safe manual or reversible-local-draft path.
>
> ### Required before implementation handoff or expansion
>
> - Candidate jobs have an explicit provisional `Inspection` state separate from `Diagnosis`; they remain local, editable, discardable, and unshareable until a Success Contract is confirmed.
> - Evidence and finding states are operational and machine-readable: observed, user-reported, inferred, stale, conflicting, absent, not assessed, insufficient, blocked, unverified, and withdrawn, with source age and non-raw references.
> - The local browser has a single-use session token, local binding, cross-site protection, analytics disabled, expiry, scope revalidation before reads, and cancellation that stops collection.
> - Cards declare permissions, dependencies, provenance, rights/license status, test status, and limitations; unreviewed Cards are visibly untrusted and never auto-imported or executed; only release-pipeline artifacts enter the signed Core catalog.
> - Moderation has explicit criteria, reviewer access/conflict rules, abuse handling, response expectations, rights attestation, secret/PII/prompt-injection/unsafe-instruction scanning, and no incentive pressure to disclose.
> - The pilot declares participant strata and exclusions, evidence consent, withdrawal/data deletion, adverse-event reporting, incident response, and synthetic-fixture red-team results before touching participant systems.
> - The handoff pack includes data-flow and trust-boundary diagrams; retention/deletion and browser security requirements; machine-readable consent, evidence, Card, and lifecycle schemas; adapter conformance and hostile fixtures; fault-injection recovery results; incident, hard-stop, withdrawal, key-rotation, and support runbooks; and explicit unresolved-risk owners.
>
> ### Deferred deliberately
>
> Consent-comprehension/accessibility testing, contract expiry or drift detection, and a broader adapter support matrix remain valuable follow-up work, but they are not substitutes for the gates above and do not weaken them.
>
> The Wayfinder is now a hardened product definition for independent review. No product implementation, deployment, publication, or Core adoption is implied by this planning record.

### Decisions-so-far index (from #347 body, one line per child)

- #348 — Reuse Dex's diagnostic, bounded-evidence, safe-change, methodology-review, and programme patterns, but build a new host-neutral capability model, adapter contract, selective Card exchange, and consent boundaries.
- #350 — Start with a macOS Claude Code Deep Adapter and a 6–8-person, majority-non-Dex Living System pilot while keeping every diagnostic contract provider-neutral.
- #349 — Make Capability Exchange a standalone local-first Dex-family product that owns diagnosis, adapters, concierge, and contribution moderation; connect it to released Core through a signed Capability Catalog.
- #351 — Assess eight universal trust capabilities without an aggregate score, using separate Capability State, Evidence Level, and Safety Boundary axes.
- #352 — Dex proposes candidate jobs from private evidence, the person confirms them, and only confirmed jobs expressed as Success Contracts drive diagnosis.
- #353 — Automate only changes with exact preview, bounded permission, validated recovery, outcome verification, and reliable undo; otherwise provide guidance and honestly refuse automation.
- #354 — Define versioned, human-readable Cards as recipes rather than records: per-use-case preview/edit/redact, immutable version consent, review-only submission, a separate Core adoption agreement, clear lifecycle/rejection, and withdrawal with honest shipped-release limits.
- #355 — Make the concierge a staged, local-first flow: inspect permission before reads, confirmed Job Map before diagnosis, jobs-first findings, one bounded adaptation with recovery and verification, and optional per-use-case contribution through the immutable Card contract.
- #356 — Keep diagnosis and adaptation account-free; use pseudonymous, version-bound contribution provenance, immediate self-service withdrawal, and a free pilot with optional recognition and deferred payment.
- #357 — Prove participant-specific job improvement for a majority of the 6–8-person pilot with a hard trust floor, then hand off one reviewed pack covering journey, domain/state, adapters, safety gates, evidence, risks, non-goals, and Fable hardening.

---

## #348 — Map existing Dex machinery onto the Capability Exchange [CLOSED]

### Question settled (verbatim)

> Which shipped, local, held, or planned pieces across Dex Core, DexDiff, the Malleable Software programme, Doctor, customization migration, and lifecycle safety can be reused for the Capability Exchange; which parts must be new; and which current status or safety boundaries constrain the product definition?

### Resolution (comment by davekilleen, 2026-07-31T09:02:24Z; titled "Answer" — research resolution) — FULL VERBATIM

> Research resolved against current primary sources.
>
> ## Answer
>
> The Capability Exchange should be a new host-neutral product layer, not a renamed DexDiff, Doctor mode, or customization migration.
>
> What to reuse:
>
> - Doctor's deterministic collector/renderer split, honest unknown state, and real-path probes.
> - The customization assessor's in-memory, bounded, sensitivity-aware inventory; explicit exclusions; partial/unknown completeness; and read-only model surface.
> - Lifecycle's exact preview, fresh approval, current-byte preconditions, single-writer transaction, receipt, verification, and rewind invariants.
> - DexDiff's job-level methodology, recipient-local regeneration, role adaptation, and account-bound browser review pattern.
> - Malleable Software's Orientation, learner-confirmed Anchor Challenge, no-fluency-score stance, evidence discipline, and 5C teaching loop.
>
> What must be new:
>
> - a versioned Host Adapter contract and conformance suite;
> - the user-confirmed Job Map, Foundation Capability taxonomy, and evidence graph;
> - separate health status and `Verified / Supported / Reported / Unknown` Evidence Level axes;
> - a closed, versioned Capability Card plus local disclosure manifest;
> - nothing-selected-by-default, per-use-case edit/redact/approve sharing;
> - a contribution intake and Core evaluation lifecycle;
> - host-specific ownership/mutation contracts and portable adaptation recipes; and
> - the private local browser concierge that keeps Diagnose, Decide, Adapt, and optional Contribute visibly separate.
>
> Hard boundary: no host-specific ownership and rewind contract means Diagnose-only. User files remain untrusted input; a preview hash proves sameness but never consent; the model never holds a write tool; model confidence never proves a capability; and Diagnosis must be read-only at the operating-system capability level.
>
> ## Status findings
>
> - Dex Core `v1.81.5` is the current release snapshot used.
> - Customization assessment/Capsule/rebuild/activation/rewind are shipped through `v1.76.1`; the architecture map's "LOCAL rebuild doorway" entry is stale.
> - DexDiff's command surface is shipped, but its redesign is parked. Its current publisher stores opaque methodology strings, publishes every diff in a review session, and sanitizes executable HTML rather than PII/secrets; its adopter also writes outside the lifecycle safe door. Reuse the pattern, not this contract.
> - Malleable Software remains product-definition work. Its learning architecture and 5C system are resolved design sources on open, unmerged branches, not a running course.
> - `/connect` is unavailable: its doorway pull request closed unmerged. Ritual Intelligence remains parked and unwired.
>
> No new Wayfinder ticket is needed: the existing child tickets already cover every question this research made precise.
>
> ## Evidence
>
> - [Cited research note](https://github.com/davekilleen/Dex/blob/research/capability-exchange-existing-machinery/docs/research/capability-exchange-existing-machinery.md)
> - [Research commit](https://github.com/davekilleen/Dex/commit/68dde1f9)
> - Branch: `research/capability-exchange-existing-machinery`
>
> Verification passed: diff check, PII/personal-config gate, founder-content gate, portable-vault contract gate, documentation-drift gate, and architecture-inventory gate.

### Amendments

None. Single resolution comment.

---

## #349 — Choose the Capability Exchange product home [CLOSED]

### Question settled (verbatim)

> Should the initial Capability Exchange live as a Dex Core capability, a standalone programme, a DexDiff extension, a Malleable Software track, or an explicitly layered combination, and which product owns the diagnostic contract, the local concierge experience, and the contribution intake?

### Resolution (comment by davekilleen, 2026-07-31T13:09:56Z) — FULL VERBATIM

> ## Resolution
>
> Dex Capability Exchange will be a standalone, local-first product in the Dex family with its own codebase and release lifecycle. It is not a Dex Core feature, a DexDiff extension, or a Malleable Software module.
>
> Capability Exchange owns:
>
> - the provider-neutral Diagnosis, Job Map, Capability Map, Evidence Level, Host Adapter, and Adaptation contracts;
> - the local browser concierge and its release lifecycle;
> - Capability Card validation, contribution preview, redaction, consent, submission status, withdrawal, moderation, and provenance;
> - the decision that a reviewed contribution is ready to become a Core Candidate.
>
> The neighbouring products have explicit participant roles:
>
> - Dex Core supplies released capabilities and receives only reviewed Core Candidates.
> - DexDiff contributes job-level methodology, adaptation, and review patterns but does not own this product.
> - Malleable Software contributes programme and teaching patterns and may refer learners into the concierge.
> - HeyDex may host identity, storage, contribution intake infrastructure, and operational services without owning the product contracts.
>
> Dex Core and Capability Exchange connect through a new signed, versioned Capability Catalog generated only from actual Core releases. Capability Exchange may refresh this knowledge automatically at startup or on a schedule, but it never treats merged, held, or experimental Core work as available. Catalog refresh does not update Capability Exchange application code, install anything into a person's system, or bypass explicit Adaptation approval.
>
> The reverse loop remains reviewed: selected Capability Card → Capability Exchange moderation → optional Core Candidate → normal Core product and release process → a future released Capability Catalog entry if Core actually ships it.
>
> This separation makes the no-migration promise structurally true while preserving a controlled two-way learning loop with Dex Core.

### Amendments

None. Single resolution comment.

---

## #350 — Choose the first host adapter and pilot cohort [CLOSED]

### Question settled (verbatim)

> Which locally inspectable personal AI system should receive the first deep diagnostic adapter, which living-system users form the first pilot cohort, what evidence qualifies a system for useful diagnosis, and what is deliberately unsupported in the first pilot?

### Resolution (comment by davekilleen, 2026-07-31T09:13:28Z) — FULL VERBATIM

> ## Resolution
>
> The first Deep Adapter will support local, folder-based Claude Code systems on macOS. This is the first implementation boundary, not the product architecture: the Job Map, Capability Map, Evidence Level, consent, Adaptation, and contribution contracts remain provider-neutral so later Host Adapters can support Codex, ChatGPT, Claude Cowork, and other environments.
>
> The first pilot cohort is 6–8 people:
>
> - 4–5 people who do not use Dex, proving standalone value and exposing capabilities Dex lacks.
> - 2–3 experienced Dex users or people with heavily customized Claude Code systems, providing a comparison baseline.
> - Technical ability is not an eligibility requirement.
>
> A pilot system qualifies as a Living System when it has been used at least weekly for roughly one month, performs at least one repeated real-world job, has inspectable or person-supplied evidence of that work, and its owner grants read-only access to the relevant local folder for Diagnosis.
>
> The explicit first-pilot support boundary is macOS plus local, folder-based Claude Code. Codex, ChatGPT, Claude Cowork, Windows, Linux, remote workspaces, and containers do not receive direct Deep Adapter verification in this pilot. People using them may still participate through exports, selected evidence, and guided interviews, with findings honestly marked Supported, Reported, or Unknown rather than Verified.
>
> This protects diagnostic depth while ensuring Claude Code assumptions never define what a Capability means.

### Amendments

None. Single resolution comment.

---

## #351 — Define the Foundation Capability set [CLOSED]

### Question settled (verbatim)

> Which universal capabilities should every trustworthy personal AI system be assessed on, and what user job, observable evidence, and safety boundary define each one without turning the result into a Dex resemblance score?

### Resolution (comment by davekilleen, 2026-08-01T08:15:14Z) — FULL VERBATIM

> ## Resolution
>
> Assess every trustworthy personal AI system against eight universal Foundation Capabilities:
>
> 1. Ownership & Portability — the person retains custody and can inspect, export, move, or replace the system. Evidence includes usable inventories, readable exports, open formats, and a demonstrated exit path. Never move, delete, or export without approval, and do not treat local file presence as proof of portability.
> 2. Privacy & Minimal Disclosure — the system accesses and reveals only what the job requires. Evidence includes declared scopes, access paths, redaction, local processing, and actual outbound-data behavior. Unknown paths remain Unknown; diagnosis does not scan secrets or unrelated private content.
> 3. Context & Orientation — the system can start or resume work with relevant, current context. Evidence comes from repeatable job examples with freshness and source visibility. More context is not automatically better; stale and inferred context must be labeled.
> 4. Durable Memory & Provenance — important knowledge survives sessions, can be sourced, corrected, and removed. Evidence requires write–retrieve–correct behavior across sessions. Chat history or configuration alone is not proof, and the system must not invent memory.
> 5. Scoped Agency & Human Control — the person can delegate within understood authority. Evidence includes permission boundaries, approvals, action receipts, and refusal of out-of-scope actions. Read access never implies permission to write, send, or expand privileges.
> 6. Safe Change & Recovery — improvements do not silently destroy what works. Evidence includes preview, snapshot or backup, apply receipt, verification, and demonstrated rollback. Diagnosis never mutates; if recovery cannot be guaranteed, adaptation is not automated.
> 7. Honest Health & Observability — the person can tell what is working, partial, disabled, broken, or unknown and why. Evidence comes from live checks, last-run information, and failure evidence. File presence alone never means healthy, and uncertainty remains visible.
> 8. Compounding & Correctability — outcomes and corrections can improve future work while the person controls what becomes permanent. Evidence includes an improvement linked to an outcome, explicit promotion, version history, and reversibility. No autonomous permanent self-modification, and one system's pattern is not treated as universal truth.
>
> Do not produce an overall score, maturity rank, or Dex-resemblance percentage. Report each capability on two separate axes:
>
> - Capability State: Working, Partial, Not demonstrated, or Unknown.
> - Evidence Level: Verified, Supported, Reported, or Unknown.
>
> Explain why each finding matters to the person's confirmed jobs and recommend one useful next move. Evidence quality is an evaluation dimension, not a ninth capability.

### Amendment (comment by davekilleen, 2026-08-04T08:33:19Z) — FULL VERBATIM

> ## Resolution amendment
>
> Dave confirmed that every Foundation Capability must be assessed on three independent axes:
>
> - **Capability State:** Working, Partial, Not demonstrated, or Unknown.
> - **Evidence Level:** Verified, Supported, Reported, or Unknown.
> - **Safety Boundary:** Safe, Overbroad, or Unclear.
>
> Safe is scoped to the assessed job and the available evidence; it is not a blanket certification of the whole system. A capability can be Working and Verified while still being Overbroad. Unknown evidence and unclear boundaries must remain visible, and the three axes must never be collapsed into an aggregate score.

Note: the amendment supersedes the original two-axis reporting instruction — three independent axes (Capability State, Evidence Level, Safety Boundary) are authoritative, consistent with #347's standing contract.

---

## #352 — Design the Job Map and evidence model [CLOSED]

### Question settled (verbatim)

> How should the concierge suggest, ask about, and confirm the jobs that matter to a person, then present Capability Map findings and Verified, Supported, Reported, or Unknown evidence in a way that feels useful rather than judgmental?

### Resolution (comment by davekilleen, 2026-08-01T08:15:18Z) — FULL VERBATIM

> ## Resolution
>
> Use a propose–confirm Job Map:
>
> 1. Dex privately inspects observable local patterns such as recurring workflows, instructions, tools, outputs, and recent activity, then proposes candidate jobs.
> 2. The concierge asks the person to confirm, edit, add, or remove those jobs.
> 3. Only user-confirmed jobs drive the diagnosis. Inferences remain suggestions, never facts.
>
> Represent every confirmed job as a small Success Contract containing:
>
> - Situation: when the person needs the job.
> - Desired outcome: the progress they actually want.
> - Success evidence: what a good result looks like in practice.
> - Boundaries: privacy, approval, and autonomy limits.
> - Importance and cadence: how much it matters and how often it occurs.
>
> Assess recent real examples against that contract rather than awarding credit for the presence of a skill, tool, integration, or configuration. Present findings with Capability State plus Evidence Level, explain them in useful non-judgmental language, and let the person correct both the job definition and supporting evidence.

### Amendments

None on this issue. Note: the #347 Fable critique later adds a required provisional `Inspection` state for candidate jobs (local, editable, discardable, unshareable until a Success Contract is confirmed).

---

## #353 — Define the cross-system Adaptation safety contract [CLOSED]

### Question settled (verbatim)

> What promises must every adaptation satisfy across different host systems, including exact preview, scope, permission, backup, verification, undo, ownership, and honest refusal where a host cannot provide those guarantees?

### Resolution (comment by davekilleen, 2026-08-01T08:18:38Z) — FULL VERBATIM

> ## Resolution
>
> Every automated Adaptation must satisfy one host-neutral transaction contract:
>
> 1. Exact preview — show the human-readable change, affected objects or files, expected benefit, and known risk before anything mutates.
> 2. Bounded scope — name the host, target, job, capability, and limits. Authority never expands implicitly.
> 3. Explicit permission — Diagnosis is always read-only. Adaptation is a separate action approved for the specific proposed change or clearly bounded batch.
> 4. Recovery point — create and validate a host-appropriate snapshot, backup, version, or equivalent before applying the change.
> 5. Ownership preservation — generated files, configuration, knowledge, and receipts remain inspectable and under the person's control; adaptation must not create hidden lock-in.
> 6. Transaction receipt — record what was proposed, approved, changed, when, by which adapter, and where recovery lives without exposing private source material.
> 7. Outcome verification — test the result against the relevant confirmed Success Contract and report Working, Partial, Not demonstrated, or Unknown with its Evidence Level.
> 8. Reliable undo — provide and test a bounded reversal path that restores the pre-change state without silently discarding later unrelated work.
> 9. Honest refusal — if the host adapter cannot provide exact preview, bounded scope, a validated recovery point, outcome verification, and reliable undo, Dex must not automate the adaptation. It may offer a clearly labelled guided recommendation or prepared instructions instead.
>
> This is a hard product boundary: no proven recovery, no automated adaptation. Host adapters may implement the guarantees differently, but none may weaken them.

### Amendments

None on this issue. Note: the #347 Fable critique later tightens this with gates 3 (adaptation allowlist, fault injection, `Unverified`/`Recovery failed` blocking) and 6 (high-impact job taxonomy fails closed to manual/reversible-local-draft paths).

---

## #354 — Design the Capability Card and Core intake contract [CLOSED]

### Question settled (verbatim)

> What exact human-readable Capability Card should a person inspect, edit, redact, and approve for one selected use case, and what review, provenance, privacy, rejection, withdrawal, and Core-consideration contract should apply after Dex receives it?

### Resolution (comment by davekilleen, 2026-08-06T11:09:08Z) — FULL VERBATIM

> ## Resolution
>
> A Capability Card is a human-readable, versioned recipe for one selected user job. It is an exchange object, not a dump of the person's existing system.
>
> ### Card content and privacy
>
> - The Card describes the selected job, the reusable method, relevant conditions, desired outcome, boundaries or safety limits, and the evidence claim supporting reuse.
> - The person sees an exact preview and can edit or redact it before submission. Nothing is selected for sharing by default.
> - Raw prompts, files, conversations, histories, and personal examples are excluded by default. Any such attachment requires a separate, explicit opt-in.
> - Submission is per use case. A Card may be shared without migrating to Dex or exposing the rest of the person's system.
>
> ### Versioning and consent
>
> - Consent attaches to one immutable Card version.
> - Any material edit to the recipe, evidence claim, boundary, disclosure selection, attribution, or permitted-use terms creates a new version with a comparison and exact preview; the new version requires fresh approval.
> - Card submission grants permission to review that version only. It does not grant permission for Core adoption, publication, attribution, recognition, reward, or other reuse.
> - Core adoption requires a separate explicit agreement covering permitted use, attribution, and any recognition or reward.
>
> ### Lifecycle and review
>
> The lifecycle is:
>
> `Draft → Submitted for review → Changes requested / Rejected / Eligible for Core consideration → Withdrawn`
>
> Withdrawal is available at any time. Review may result in changes requested, rejection, or eligibility for Core consideration; eligibility is not adoption and never implies that Core will ship the capability.
>
> A rejection must give a specific plain-language reason, say whether revision could help, and offer a new-version or appeal route. It must not imply Core adoption.
>
> ### Withdrawal and Core boundary
>
> Withdrawal immediately stops new review, reuse, attribution, and distribution where feasible. The product must retain only the minimum audit record needed to honour the withdrawal. It must disclose before the separate Core-adoption agreement that withdrawal cannot falsely promise to erase a capability from an already-shipped release.
>
> Any Core Candidate still goes through the normal Core review and release process. The Exchange never auto-adopts a Card into a user's system or into Core; only an actual signed/versioned Core release can become part of the future Capability Catalog.
>
> This resolves the Capability Card and Core intake contract. The next unblocked frontier is #355, the one-command concierge journey.

### Amendments

None on this issue. Note: the #347 Fable critique later adds gate 4 (Card permission/withdrawal state machine, schema rejecting secrets/raw examples/unique paths/third-party confidential material by construction) and required handoff items on Card declarations and moderation.

---

## #355 — Prototype the one-command concierge journey [CLOSED]

### Question settled (verbatim)

> What should the full local concierge experience feel like from the trusted doorway command through inspection permission, Job Map confirmation, read-only Diagnosis, Capability Map review, selected Adaptation, outcome verification, and optional per-use-case contribution?

### Resolution (comment by davekilleen, 2026-08-06T15:19:57Z) — FULL VERBATIM

> ## Resolution
>
> The concierge is a staged, local-first journey that keeps the person's existing system in place and makes every trust boundary visible.
>
> ### Journey contract
>
> 1. **Trusted doorway.** One terminal command opens a private local-browser concierge. The command does not silently begin inspection or adaptation.
> 2. **Inspection permission.** The first screen is unscanned and plain-language. It names the adapter, exact folders or artifacts it will inspect, what stays local, what it will not read, and what the next read-only step can do. No adapter read occurs until the person explicitly approves that scope. They can decline and leave without changing the system.
> 3. **Private evidence collection.** After approval, the adapter performs only the agreed read-only inspection. Evidence remains local by default. If a deep adapter is unavailable, the concierge uses guided interview or export-assisted evidence and labels the limitations honestly; it does not pretend to have inspected what it cannot verify.
> 4. **Job Map confirmation.** Dex privately proposes candidate jobs from the evidence. The person confirms, edits, adds, or removes jobs. Each retained job is expressed as a Success Contract: situation, desired outcome, success evidence, boundaries, and importance or cadence. No capability diagnosis is shown until the person confirms the jobs.
> 5. **Read-only Diagnosis.** Diagnosis runs only against confirmed Success Contracts and the approved evidence scope. It produces separate Capability State, Evidence Level, and Safety Boundary findings across the eight Foundation Capabilities. There is no aggregate score, resemblance rank, or hidden pass/fail verdict.
> 6. **Jobs-first Capability Map.** The map is organized around the person's confirmed jobs, with the relevant Foundation Capability findings nested inside each job. Each finding shows its evidence, uncertainty, boundary, and practical implication so the person can inspect the reasoning rather than accept a system-wide label.
> 7. **Selected Adaptation.** The default unit is one bounded adaptation at a time. Before any change, the concierge shows the exact proposed change, affected scope, ownership impact, recovery proof, and expected outcome. The person gives explicit consent. If proven recovery is unavailable, the concierge provides guidance and refuses automated change.
> 8. **Receipt and outcome verification.** After an approved change, the concierge records a local receipt, validates recovery and ownership, checks the Success Contract's outcome evidence, and makes undo available. A failed or ambiguous result stops the chain and returns to recovery or honest diagnosis; it does not silently continue to another change.
> 9. **Continue or contribute.** After a verified outcome, the person may stop, inspect another job, or choose a separate per-use-case contribution. Contribution uses the immutable, previewable Capability Card contract resolved in #354: recipe rather than records, exact edit/redact, no raw material by default, version-specific consent, review permission only, and a separate Core-adoption agreement.
>
> Every stage makes the next action, scope, data boundary, and exit path explicit. The concierge never changes the user's system, shares evidence, or contributes a Card merely because the person completed an earlier stage. Account, identity, provenance, attribution, recognition, and payment questions remain deliberately deferred to #356.
>
> This resolves the one-command concierge journey and establishes the first implementation handoff shape without building the product during Wayfinder planning. The next unblocked frontier is #356, the account, provenance, and value-exchange model.

### Amendments

None on this issue. Note: the #347 Fable critique later adds local-browser security requirements (single-use session token, local binding, cross-site protection, analytics disabled, expiry, scope revalidation before reads, cancellation that stops collection).

---

## #356 — Decide the account, provenance, and value-exchange model [CLOSED]

### Question settled (verbatim)

> Which parts of the Capability Exchange should work without an account, when identity or authentication becomes necessary, how contribution provenance and withdrawal should work, and whether diagnosis, adaptation, attribution, recognition, or payment create the right value exchange?

### Resolution (comment by davekilleen, 2026-08-06T15:49:54Z) — FULL VERBATIM

> ## Resolution
>
> The Capability Exchange keeps private diagnosis and adaptation account-free. An account or identity becomes necessary only when a person chooses to contribute a Capability Card or explicitly chooses attribution, recognition, or payment.
>
> ### Account boundary
>
> - A person can open the local concierge, inspect their existing system, confirm a Job Map, receive diagnosis, and apply bounded adaptations without creating an account or signing in.
> - No account is required to improve the person's own system, and the Exchange does not turn private diagnosis into an identity dossier or cloud account by default.
> - Identity is requested only at the contribution boundary, where it is needed to manage the contribution relationship, withdrawal, and any explicit attribution, recognition, or payment choice.
>
> ### Provenance
>
> - Each contributed Card version carries a stable, pseudonymous contributor reference and version-bound provenance sufficient for review: how the method and evidence claim were derived, what adapter or evidence mode was used, and what the person explicitly approved.
> - The person's name and contact details remain private unless they separately choose named attribution or another disclosure.
> - Provenance describes the reusable method and evidence claim; it does not require uploading raw prompts, files, conversations, histories, or personal examples.
> - The contributor reference is tied to the immutable Card version and its consent record, so review, withdrawal, and attribution decisions cannot silently migrate to a different version.
>
> ### Withdrawal
>
> - A contributor can withdraw any Card version directly and at any time.
> - Withdrawal immediately stops new review, reuse, attribution, and distribution where feasible. The Exchange retains only the minimum audit record required to honour the withdrawal and explain the state honestly.
> - Withdrawal must disclose before contribution that it cannot promise to erase a capability from an already-shipped Core release or downstream copy that the Exchange no longer controls.
> - The account exists to make this control durable; it does not grant permission to inspect or modify the person's local system.
>
> ### Value exchange
>
> - The first pilot is free for diagnosis and adaptation.
> - Contribution has no automatic payment or bounty. Attribution and recognition are optional choices made by the contributor, never a condition of diagnosis or contribution review.
> - Any payment model is deferred until the Exchange has demonstrated real reuse value and can define fair governance, eligibility, provenance, and payout rules without distorting contribution quality.
> - The immediate exchange is explicit and two-way: the person receives private, actionable improvement to their existing system; Dex receives only the selected, previewed, consented Card that the person chooses to contribute.
>
> This resolves the account, provenance, withdrawal, and first-pilot value-exchange model. The next unblocked frontier is #357, pilot success and implementation handoff criteria.

### Amendments

None. Single resolution comment.

---

## #357 — Define pilot success and implementation handoff criteria [CLOSED]

### Question settled (verbatim)

> What observable outcomes would prove the first pilot improves the person's existing system, preserves trust and control, produces useful learning for Dex, and leaves a product definition complete enough to hand off for implementation?

### Resolution (comment by davekilleen, 2026-08-06T17:20:19Z) — FULL VERBATIM

> ## Resolution
>
> The pilot succeeds only when the person's existing system demonstrably improves while the product's privacy, ownership, recovery, and control promises remain intact.
>
> ### Primary success gate
>
> - Every participant enters with at least one repeated real job expressed as a Success Contract.
> - The primary proof is outcome plus trust: at least half plus one of the 6–8 participants must show meaningful improvement on a repeated job, and no severe privacy, consent, ownership, recovery, or control failure may be accepted as a normal pilot outcome.
> - Capability Cards contributed to Dex are useful secondary learning, never the pilot's success gate. A person may complete a valuable pilot without contributing anything.
>
> ### Outcome evidence
>
> - Each participant defines the evidence of success for their own Success Contract: situation, desired outcome, observable signal, boundaries, importance, and cadence.
> - The pilot records a baseline before adaptation and a follow-up after the changed system has been used in the real job. Evidence can combine observable job signals with the participant's informed assessment, but it is not self-report alone by default.
> - There is no universal score across jobs and no Dex-resemblance ranking. Results are reported as contract-specific before/after outcomes plus the confidence and evidence limits that apply.
>
> ### Trust and safety floor
>
> Any unapproved read, share, or change; false evidence claim; ownership violation; or adaptation that cannot recover and be honestly explained automatically stops the affected pilot path and triggers review. The pilot does not trade away a trust promise to preserve an attractive outcome metric.
>
> The review records what happened, contains the issue, restores or verifies ownership where possible, and determines whether the product definition or pilot must change. No raw personal system content is required for Dex learning.
>
> ### Learning for Dex
>
> The pilot also records provider-neutral learning about adapter coverage, evidence quality, diagnosis usefulness, adaptation boundaries, recovery, and which reusable methods people choose to contribute. The learning output is normalized and privacy-preserving; it does not turn participant systems or histories into a dataset.
>
> ### Implementation handoff bar
>
> Implementation begins only after one reviewed handoff pack contains:
>
> - the end-to-end concierge journey and explicit stage/exit boundaries;
> - the domain and state model for jobs, evidence, findings, adaptations, receipts, Cards, consent, provenance, and withdrawal;
> - the host adapter contract and honest fallback behaviour;
> - testable privacy, consent, ownership, recovery, undo, verification, and refusal gates;
> - the pilot protocol, baseline/follow-up evidence template, trust incident procedure, and success threshold;
> - the observed pilot evidence, unresolved risks, assumptions, and explicit non-goals; and
> - the post-plan Fable critique and the decisions made in response to it.
>
> This resolves the pilot success and implementation handoff criteria. The Wayfinder product definition is now ready for the planned independent Fable critique and hardening pass before implementation work begins.

### Amendments

None on this issue. The subsequent Fable critique lives on #347 (2026-08-06T17:31:05Z, reproduced in full above) and adds predeclared pilot-measurement requirements (gate 5) plus the expanded "Required before implementation handoff or expansion" list that supplements this issue's handoff bar.

---

## Cross-cutting notes for the handoff pack

- Only #351 has a formal in-issue amendment (three-axis assessment adding Safety Boundary: Safe / Overbroad / Unclear).
- The #347 Fable critique (2026-08-06) is the final hardening layer: its six non-negotiable gates and "Required before implementation handoff or expansion" items constrain #350 (adapter containment), #352 (Inspection state), #353 (allowlist/recovery/high-impact taxonomy), #354 (Card state machine/schema), #355 (browser security), and #357 (predeclared measurement, handoff pack contents). It explicitly states the core direction "should not be weakened."
- #357's handoff bar requires the pack to include "the post-plan Fable critique and the decisions made in response to it."
- #348's evidence branch: `research/capability-exchange-existing-machinery` (commit 68dde1f9), doc `docs/research/capability-exchange-existing-machinery.md`.
