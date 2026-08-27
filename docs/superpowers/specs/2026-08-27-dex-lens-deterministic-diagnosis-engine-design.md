# Dex Lens deterministic diagnosis engine and MCP design

**Date:** 2026-08-27
**Status:** Implemented on `main` as Lens v0.1.13 after Dave approved
publication on 2026-08-27. Signed public download follows the release
workflow. This document does not hand-edit the live installer.
**Supersedes:** The orchestration and report-truth portions of
`2026-08-26-dex-lens-complete-diagnosis-eval-design.md`
**Keeps:** Its read-only containment, bounded discovery, operational-state,
signed-catalogue, complete-ledger, reciprocal-value and sanitised-evaluation
contracts

## Executive decision

Dex Lens will become one deterministic local diagnosis engine with two thin
adapters:

1. a command-line adapter that works in any terminal or agent harness; and
2. a local MCP adapter that lets Claude, Codex and other MCP-compatible
   assistants drive the same engine through structured tools.

MCP is the plug, not the brain. The engine owns scope identity, evidence,
catalogue identity, stage transitions, catalogue accounting, factual report
content and durable run state. The adapters are deliberately shallow: they
translate requests and return typed engine views, but cannot reinterpret facts
or advance a run past a missing consent or evidence requirement.

The conversational skill remains the human guide. It explains what is
happening, asks useful questions and turns grounded findings into natural
language. It no longer owns the checklist, arithmetic, run state, factual
claims, decision state or closing sequence.

## Why this second design is necessary

The complete-diagnosis work released in Lens v0.1.11 fixed genuine structural
problems. It added four-class discovery, operational states, a complete
catalogue ledger, grounded praise, reciprocal value and a synthetic legacy
system evaluation. Those changes remain valuable.

The first full real-world session after that release exposed a second layer of
failure: the deterministic pieces existed, but the model still assembled and
narrated them manually.

The supplied session contains 595 messages, 183 tool calls and 183 tool
results over three hours and twenty minutes. The initial diagnosis reached a
saved report after roughly fourteen minutes; the remaining session mixed
follow-on repair and building work into the same conversational thread.

The decisive contradiction is machine-verifiable:

- the final ledger contained 115 entries;
- its disposition counts included 80 `not-assessed`, 17 `not-relevant`, eight
  `shared`, three `worth-borrowing`, three `fragile-or-contradictory`, two
  `strong-here` and two `dex-should-learn`;
- the report nevertheless stated that 93 capabilities were already covered,
  19 were rejected and three were recommended; and
- `dex-lens reports check` approved that report as ready to save.

The report numbers came from an earlier draft and survived after the ledger
was rebuilt. The current gate validates the Markdown shape and independently
validates the ledger, but never derives or reconciles report claims against
that ledger. A syntactically complete report can therefore contradict its own
evidence.

Other observed failures reinforce the same diagnosis:

- observations from the named folder and a global assistant folder were
  grouped by label, so an old system can appear to inherit a newer global
  capability;
- the inventory count was described as a capability count even though it
  included manifests and working copies;
- the person had to ask whether the Lens walkthrough had finished;
- the required sharing choice was skipped until the person prompted for it;
- a later summary recorded an option as taken without a corresponding user
  choice; and
- long follow-on work produced shifting completion claims while jobs were
  still running.

These are not primarily prompt-writing defects. They are missing ownership
inside the product. Facts, state and completion still live in a probabilistic
conversation when they need to live in a deep deterministic module.

## Product outcome

A person should be able to ask any supported assistant:

> Use Dex Lens to understand my setup, tell me what is especially good, what
> Dex should learn from it, and the few Dex ideas that would genuinely help.

Lens should then complete a bounded, read-only diagnosis that:

1. cannot silently skip a catalogue capability;
2. cannot claim stronger coverage than its evidence proves;
3. keeps the origin of every observed capability visible;
4. understands skills, MCP servers, tools, integrations, scheduled work,
   health machinery and system engines as parts of human-meaningful systems;
5. explains newer Dex systems in plain language when version distance is
   known;
6. credits the person's strongest methods and identifies ideas Dex should
   learn;
7. separates diagnosis from any repair, installation or sharing action;
8. resumes honestly after interruption; and
9. produces the same factual result through the command line and MCP.

The person may still receive a thoughtful, human report. Deterministic does
not mean robotic. It means the prose cannot alter the underlying truth.

## Product vocabulary

- A **run** is one diagnosis bound to one consented scope snapshot, one exact
  catalogue, one engine version and one fixed assessment time.
- A **source root** is one separately approved folder or live-state surface.
- **Provenance** records which source root and ownership class produced an
  observation without retaining a raw private path.
- A **capability family** is a plain-language system outcome supported by one
  or more detailed catalogue entries, such as “Dex watches its own health.”
- A **specialist proposal** is a bounded, evidence-referenced suggestion from
  an assistant or sub-agent. It is untrusted input until the engine validates
  it.
- A **fact block** is report content generated mechanically from typed engine
  output. A model may not rewrite its numbers, identities or state.
- A **decision receipt** records a choice made through the local consent and
  decision surface. An assistant assertion is not a receipt.
- A **share receipt** records a confirmed send through a separately authorised
  sharing path. A preview or an assistant claim is not a send.

## Architecture

```text
                existing local consent surface
                         │
                         ▼
                 ApprovedScopeReceipt
                         │
      ┌──────────────────┴──────────────────┐
      │                                     │
 command-line adapter                 local MCP adapter
      │                                     │
      └──────────────┬──────────────────────┘
                     ▼
          DeterministicDiagnosisEngine
          one small external interface
                     │
        ┌────────────┼──────────────┐
        ▼            ▼              ▼
  run state     typed result    canonical report
    store        + ledger         + receipts
        │            ▲              ▲
        │            │              │
        └──── validated specialist proposals
             (optional, evidence-bounded)
```

The central module is intentionally deep. Its external interface is small;
scope validation, collection, catalogue verification, proposal validation,
state transitions, reconciliation, rendering and checkpointing stay behind
that interface.

### External interface

The first implementation exposes this conceptual interface:

```python
class DeterministicDiagnosisEngine(Protocol):
    def prepare(self, request: PrepareDiagnosisRequest) -> DiagnosisRunView: ...
    def status(self, run_id: str) -> DiagnosisRunView: ...
    def advance(self, run_id: str) -> DiagnosisRunView: ...
    def submit(self, run_id: str, proposal: SpecialistProposal) -> DiagnosisRunView: ...
    def result(self, run_id: str) -> DiagnosisResult: ...
```

`prepare` records candidate folders without reading them and returns the
existing local consent action. It cannot issue an approval receipt. The engine
receives that receipt only from the local consent authority after the person
approves the exact scope. `status` reports proved progress without advancing
anything. `advance` performs the next lawful deterministic transition and is
idempotent. `submit` accepts optional semantic help but cannot alter evidence
or state directly. `result` returns only after the run is closed and all
required reconciliation checks pass.

The command-line and MCP adapters can call `prepare`, but they cannot call or
impersonate the consent authority. A model cannot turn its own assertion that
the person agreed into scope approval.

The exact Python implementation may use a concrete class rather than a
`Protocol`; this interface describes what callers and tests are allowed to
know.

### Immutable run input

Preparation creates a pending, non-reading record. Each checkpoint binds the
artifacts that exist at that stage. By `jobs-confirmed`, the engine has every
lawful input required for its pure comparison path and materialises this
content-bound execution input:

```python
class DiagnosisInput(InventoriedModel):
    run_id: str
    engine_version: str
    input_schema_version: str
    adapter_version: str
    approved_scope_receipt: ApprovedScopeReceipt
    fingerprint_sha256: str
    catalogue_version: int
    catalogue_sha256: str
    catalogue_bytes: bytes
    confirmed_jobs: tuple[SuccessContract, ...]
    previous_decisions: tuple[DecisionReceipt, ...]
    assessed_at: datetime
```

The catalogue is the exact signature-verified byte sequence, not a mutable
URL or a reloaded “latest” file. `assessed_at` is fixed when the run is
prepared, so staleness rules cannot change halfway through a run. Before the
execution input is complete, scope, fingerprint and catalogue digests are
added monotonically to their own stage checkpoints. A changed
scope identity, catalogue hash, fingerprint hash or engine version creates a
new input identity rather than quietly continuing the old run.

## Deterministic truth and bounded judgement

Lens cannot make every semantic comparison mathematical. Deciding whether
two differently written methods fulfil the same human job may require
judgement. The design makes the division honest.

The engine alone owns deterministic truth:

- consented source identities and scope limits;
- observations and their provenance;
- catalogue identity and availability;
- operational state;
- entry counts and disposition counts;
- whether every catalogue identity has exactly one disposition;
- whether an evidence reference belongs to this run;
- whether a recommendation is available and relevant;
- whether a user decision or share receipt exists;
- stage transitions; and
- all factual report blocks.

An assistant or specialist may propose:

- candidate mappings between observations and human capabilities;
- method-comparison notes;
- candidate strengths;
- a reciprocal lesson for Dex;
- candidate fragility explanations; and
- candidate recommendation rationales.

Every proposal is typed, bounded and refers only to evidence identities the
engine assigned. The engine rejects unknown references, unsupported states,
unavailable catalogue entries, duplicate claims, more than three
recommendations and claims whose source provenance has been collapsed.

When specialists disagree, evidence is missing or the proposal cannot clear
the rule, the result remains `Unknown` or `not-assessed`. The engine never
fills a gap with the most confident prose.

## Provenance and cross-root identity

The current observation identity `(kind, identity)` is insufficient. It
forces same-named items from different roots either to collide or to be
grouped before their origin is understood.

Every observation gains an immutable source reference:

```python
class SourceClass(StrEnum):
    VAULT_AUTHORED = "vault-authored"
    USER_GLOBAL = "user-global"
    HARNESS_BUNDLED = "harness-bundled"
    PLUGIN_OR_VENDOR = "plugin-or-vendor"
    WORKING_COPY = "working-copy"
    GENERATED = "generated"
    LIVE_SYSTEM = "live-system"


class SourceProvenance(InventoriedModel):
    source_id: str
    source_class: SourceClass
    scope_reference: str
    relative_reference: str
    content_digest: str | None
```

`scope_reference` is a non-reversible local identifier from the consent
receipt. `relative_reference` is bounded and secret-checked. Raw absolute
paths never enter the fingerprint, report or MCP wire.

Observations are unique by `(kind, identity, source_id)`. Same-name items may
be folded into one human capability only after an explicit equivalence rule
or a validated method comparison. A newer global skill cannot make an older
vault-local skill current merely because their labels match.

Working copies remain visible for housekeeping but are ineligible to prove an
active capability unless separately approved as an active source.

## Durable run state

The prompt no longer owns the checklist. Each run follows a closed state
machine:

```text
created
  → scope-approved
  → captured
  → catalogue-verified
  → jobs-confirmed
  → compared
  → rendered
  → checked
  → saved
  → closed
```

Each transition:

- has one typed prerequisite set;
- writes one atomic checkpoint outside all inspected roots;
- is idempotent for the same input digest;
- refuses to run after a terminal failure or input drift;
- records the engine version and previous-state digest; and
- returns the next required action in plain language.

An interrupted run resumes at the last verified checkpoint. It does not
repeat collection or claim to have completed a later stage. If the approved
root identity changes, the run becomes stale and Lens offers a new run.

`closed` is a hard product boundary. A diagnosis process exposes no repair,
installation, enablement, deletion, adaptation or external-send capability.
Any follow-on work begins as a separate, explicitly authorised flow with a
new receipt.

## Report model and reconciliation

Markdown is an output format, not the source of truth. The engine first builds
a typed `ReportModel`:

```python
class LedgerSummary(InventoriedModel):
    total: int
    by_disposition: dict[Disposition, int]
    assessed: int
    unknown: int


class ReportModel(InventoriedModel):
    run_identity: RunIdentity
    strongest_findings: tuple[GroundedFinding, ...]
    reciprocal_findings: tuple[GroundedFinding, ...]
    reliability_findings: tuple[GroundedFinding, ...]
    version_delta: tuple[CapabilityFamilyDelta, ...]
    recommendations: tuple[GroundedRecommendation, ...]
    later_families: tuple[CapabilityFamilySummary, ...]
    ledger_summary: LedgerSummary
    limits: tuple[str, ...]
    decisions: tuple[DecisionReceipt, ...]
    share_state: ShareState
```

`LedgerSummary` is calculated from the final ledger. There is no public
constructor that accepts independent numbers. Report rendering inserts
canonical fact blocks for catalogue version, totals, dispositions, limits,
decisions and share state.

The model may improve connective wording around those blocks, but it cannot
rewrite or duplicate their factual content. `reports check` parses the
embedded run and ledger digests, re-renders the fact blocks and requires an
exact match before save.

A report with 80 `not-assessed` entries therefore cannot render “93 already
covered.” Changing either the prose claim or one ledger disposition makes
check and save fail.

## Capability families and version distance

The detailed signed catalogue remains essential for proof, but a first-time
reader should not have to assemble a product story from 115 technical rows.
Lens groups related entries into capability families such as:

- **Dex watches its own health** — Doctor, scheduled checks and proactive
  reliability engines;
- **Connected tools stay connected** — provider discovery, connection health,
  refresh and tool-server surfaces;
- **Safe updates you can rewind** — transaction safety, customisation
  preservation and recovery;
- **People context stays alive** — person pages, relationship signals,
  meeting context and memory;
- **Tasks stay in sync** — external task systems, completion flow, review and
  links to people, companies and goals; and
- **Share and adopt ways of working** — comparison, previews, contributions
  and reviewable adoption.

Families are not inferred from marketing prose. They become signed catalogue
data owned by Dex Core, with entry membership, plain-language outcome,
availability and release lineage. Lens supports the older catalogue shape
until Core releases the additive family contract.

When the inspected system's lineage and version are proven, the report adds
“What has changed since your version.” It presents family-level changes, not
a release-note dump. It preserves two truths:

1. only released, available capabilities may be presented as usable now; and
2. held or parked foundations may be explained as context but never pitched
   as something the person can borrow.

For example, the connection-management foundation may be recognised and
explained while its person-facing connection doorway remains held. Lens says
that plainly rather than advertising it or silently erasing the story.

## Specialist agents and sub-agents

Specialists improve recall and judgement; they never become authorities.
The engine can issue bounded evidence shards for these roles:

1. **Tools and integrations specialist** — MCP declarations, safely known
   tools, provider registries and connection lifecycle.
2. **Automations and live-state specialist** — written, installed, loaded,
   recent and outcome-verified scheduled work.
3. **Strength and reciprocal specialist** — distinctive, transferable methods
   the person already does well.
4. **Contradictions and reliability specialist** — rules, live outcomes,
   conflicts and silent failure patterns.
5. **Release-distance specialist** — capability-family differences between a
   proven older lineage and the signed current catalogue.
6. **Sceptical reconciler** — challenges proposed equivalence, praise and
   recommendations against provenance and evidence.

Each specialist receives only:

- a fixed run identity;
- a bounded list of safe observations;
- the relevant signed catalogue slice;
- the closed proposal schema; and
- a maximum output size.

It returns structured proposals with evidence IDs. It cannot read arbitrary
paths, call mutation tools, access secrets, advance run state, alter another
specialist's output or author report counts.

On a host with sub-agent support, these shards may run in parallel. On a host
without it, the same host assistant may process them sequentially. A run is
complete even if no specialist is available: unmade semantic comparisons stay
Unknown, while deterministic catalogue accounting still completes.

## Command-line adapter

The command-line adapter is the universal route and the reference adapter for
conformance tests. It exposes JSON on stdout and sends human diagnostics to
stderr:

```text
dex-lens diagnosis prepare --root <folder> [--additional-root <folder>]
dex-lens diagnosis status --run <id> --json
dex-lens diagnosis advance --run <id> --json
dex-lens diagnosis submit --run <id> --proposal <json-file>
dex-lens diagnosis result --run <id> --format json|markdown
```

`prepare` creates no fingerprint. It starts or reuses the existing local
consent surface and returns a run ID plus the local approval action. Collection
cannot begin until the local approval receipt exists.

The command line accepts no option that signs, sends, installs, repairs or
modifies the inspected system.

## MCP adapter

The MCP server is a local stdio process built with the official Python MCP SDK
stable line. It contains no diagnosis rules and uses the same application
storage and engine interface as the command line.

It exposes a deliberately small read-only tool set:

- `prepare_diagnosis` — create a pending run and return the local consent
  action without reading the target;
- `get_diagnosis_status` — return the current stage, completed proof and next
  required action;
- `advance_diagnosis` — perform the next lawful deterministic step;
- `submit_specialist_proposal` — offer typed, evidence-referenced semantic
  help for validation; and
- `get_diagnosis_result` — return the closed typed result or canonical report.

There is no generic shell tool, filesystem tool, network tool or mutation
tool. The server does not expose adaptation or sharing. Stdout is reserved for
the MCP wire; logs go to stderr.

The MCP adapter accepts a run ID rather than raw unapproved paths after
preparation. Both adapters return the same canonical JSON for the same run and
proposal set.

Installer registration is a later delivery decision. The server must first
pass direct-engine, command-line and MCP conformance tests. No host
configuration is changed merely because the package contains an MCP entry
point.

## Decision and sharing integrity

Diagnosis records three distinct states:

- `offered` — an option was shown;
- `chosen` — the person selected it through the local decision surface; and
- `completed` — a separately authorised action returned a receipt.

The report may say “taken” only for a confirmed `chosen` or `completed`
decision receipt, using wording appropriate to the state. It may say “shared”
only when a share receipt records the destination class, exact disclosed-byte
digest and confirmed response.

Previewing a contribution, writing a draft or an assistant saying it shared
something never changes share state.

The diagnosis close always includes:

1. the strongest grounded thing the person is already doing;
2. what Dex should learn, or the exact honest empty answer;
3. the single best first move, if one cleared the bar;
4. where the report was saved;
5. how to return to the run; and
6. the separate sharing and future-watch choices.

This close is generated from `ReportModel`; the skill cannot silently drop a
step because it thinks the person does not need it.

## Evaluation strategy

### Golden replay from the supplied session

The real session becomes a sanitised event-and-state replay, not a copy of the
private vault or transcript. The committed fixture preserves only:

- 115 catalogue identities using invented labels where needed;
- the exact disposition-count relationship that exposed the contradiction;
- multiple same-name items from different source classes;
- configured MCP servers with unknown tools;
- written versus live scheduled work;
- one strong reciprocal method;
- decision and share state transitions;
- interruption points; and
- synthetic evidence excerpts and canaries.

No real name, absolute path, private prose, token, credential, session URL or
machine identifier enters Git.

### Conformance matrix

The same canonical input is exercised through:

- the engine directly;
- the command-line adapter;
- the MCP adapter in memory;
- an MCP stdio subprocess;
- a fake Claude-style caller; and
- a fake Codex-style caller.

Given the same engine input and validated specialist proposals, the canonical
`DiagnosisResult` bytes must be identical. Host wording outside the canonical
result may differ.

### Hard acceptance failures

The release candidate fails when any of these occurs:

- a ledger and report count disagree;
- any catalogue identity is missing or duplicated;
- 80 `not-assessed` entries can be narrated as broad coverage;
- a same-name item from a different source root silently proves equivalence;
- an evidence reference does not belong to the exact fingerprint;
- a configured MCP server implies tools that were not enumerated;
- written scheduled work is called active without live evidence;
- a held or parked Dex capability is recommended as available;
- a decision is recorded without a decision receipt;
- a preview is recorded as shared;
- diagnosis can call or import a mutation path;
- an interrupted run restarts or skips a stage silently;
- any private canary reaches a fingerprint, report, checkpoint or MCP message;
- command-line and MCP results differ for the same input; or
- the close omits strengths, reciprocal value, next move, report location or
  sharing choice.

## Delivery sequence

The implementation is delivered in independently testable slices:

1. **Report truth:** make `ReportModel` and ledger-derived facts the only save
   path; add decision/share receipt integrity.
2. **Provenance:** add source identity and ownership class without weakening
   the current collector bounds or secret rules.
3. **Durable engine:** add immutable input identity, atomic checkpoints,
   stage transitions, resume and the hard closed boundary.
4. **Capability families:** add Lens compatibility for the additive family
   contract, then let Core publish exact signed family membership and release
   lineage through its own review and release sequence.
5. **Adapters:** make the command-line adapter pass conformance, then add the
   thin local MCP adapter over the same interface.
6. **Specialists:** add bounded proposal shards and the sceptical reconciler;
   keep them optional for deterministic completeness.
7. **Golden replay:** run the sanitised real-session replay across direct,
   command-line and MCP routes, including interruption and hostile mutations.
8. **Dogfood:** use a signed candidate against the real system read-only and
   compare the result with the adjudicated expectations.

No slice requires public release. Installer registration, beta promotion and
publication each remain separate explicit decisions after the full candidate
passes.

## Acceptance criteria

The approved design is implemented only when all of the following are proved:

- one engine interface owns the complete run through both adapters;
- every factual report claim is derived from typed result data;
- report and ledger identities and counts reconcile exactly at check and save;
- provenance prevents cross-root same-name inheritance;
- every signed catalogue entry has exactly one final disposition;
- all supported MCP servers, scheduled automations and system engines retain
  their exact identities and strongest proved operational states;
- capability-family version delta explains material newer systems without
  advertising held work;
- at most three immediate recommendations survive, alongside grounded praise
  and reciprocal value;
- diagnosis writes only to guarded Lens application storage outside every
  inspected root;
- decision and share claims require their corresponding receipts;
- an interrupted run resumes from the last verified stage;
- direct, command-line and MCP canonical results are byte-identical for the
  same inputs;
- the sanitised real-session replay catches the observed false-completeness,
  provenance, sequencing and closing failures;
- full tests, lint, packaging, containment, egress and signed-release checks
  pass before any publication decision; and
- a fresh public-install rehearsal passes before beta testers are directed to
  a release containing the new engine.

### Candidate proof, 2026-08-27

The implementation candidate on draft pull request #46 proves the engine
interface, ledger-derived facts, receipt-backed decisions, atomic resume,
specialist validation without authority, and byte-identical direct/CLI/MCP
replay. GitHub CI is green at `572f2d8`, including the exact pilot-build
G1–G6 + R3 gate. Capability-family version delta remains disabled until a
signed family contract exists. Signed-release checks and a public-install
rehearsal are still required before any publication decision. This document
does not authorise merge or release.

## Explicitly out of scope

- Automatic repair, installation, enablement, deletion or scheduling during
  diagnosis.
- Giving an MCP server arbitrary filesystem, shell or network access.
- Treating specialist model output as evidence.
- Uploading raw fingerprints, reports, transcripts or private vault content.
- Calling a marketing feature available when Core marks it held or parked.
- Replacing human judgement with a maturity score.
- Automatically registering the MCP server in every installed assistant.
- Merging, releasing or changing the public installer without a later explicit
  product-owner decision.

## Alternatives rejected

### Improve the skill only

Rejected. The released skill already contained the correct instructions and
still approved a report that contradicted its ledger. More prompt text cannot
own arithmetic, durable state or provenance.

### Deterministic engine with command line only

Viable as an internal milestone, but incomplete as the product direction.
Claude, Codex and other structured hosts would each need their own prompt-led
translation, recreating drift at the adapter seam.

### Put orchestration inside the MCP server

Rejected. It would make MCP-capable hosts authoritative while leaving other
harnesses on a different path. MCP remains an adapter over the same engine,
not the implementation of the engine.

### Let specialist agents write the report directly

Rejected. Parallel specialists can improve recall, but direct report writing
would recreate the exact stale-count and skipped-stage failure this design is
intended to remove.
