# Dex Lens complete diagnosis and evaluation design

**Date:** 2026-08-26
**Status:** Product-owner approved; private legacy-vault fingerprint and
targeted adjudication complete; implementation is planned but has not started
**Scope:** Read-only discovery, the private evidence fingerprint, comparison
against Dex's signed Capability Catalog, report quality, and regression
evaluation

## Outcome

Dex Lens must understand a personal AI system as a working whole. It should
not reduce that system to a list of skills, nor reduce Dex to catalogue entry
names. A good Diagnosis identifies the jobs the person can actually fulfil,
the tools and integrations they can reach, the work that happens without a
prompt, the health and safety machinery around that work, and the useful
ideas Dex should learn from the person.

The result should feel like a perceptive second opinion:

1. lead with specific, evidence-backed strengths;
2. say what Dex could learn from this system;
3. recommend at most three genuinely useful additions from Dex;
4. keep fragility and housekeeping separate from capability gaps; and
5. show that every relevant Dex capability was considered without dumping a
   114-row checklist on the reader.

The person should not need to understand MCP, launchd, hooks, or catalogue
schemas. When one of those terms is necessary, Lens explains what it means in
plain language at the point of use.

## Why the present Diagnosis is not good enough

The 2026-08-26 dogfood run compared against a signed 114-entry catalogue,
but its strongest conclusion was that the vault already had almost
everything. That conclusion was not earned.

The current path has five structural weaknesses:

1. **Discovery is narrower than the system.** MCP declarations are recognised
   only in a small set of folder-local JSON files. Scheduled work is recognised
   only when a plist or crontab happens to sit inside the inspected folder.
   Global assistant configuration, harness-specific configuration, hooks,
   services, integration registries, live job state, and run evidence are not
   covered consistently.
2. **Counts are mistaken for capability.** Twenty-nine connected tools do not
   prove integration lifecycle management. Nineteen hooks do not prove
   proactive health monitoring. Presence is evidence of configuration, not
   evidence that a job is fulfilled.
3. **Dex's implementation detail is presented as the product meaning.** A
   catalogue entry is useful release evidence, but several entries may
   collectively support one human Capability. Conversely, one broad entry may
   need several kinds of evidence before Lens can say the Capability exists.
4. **The report contract is one-way.** The template permits praise, but the
   save gate does not require a substantive strength or a reciprocal idea for
   Dex. A long run can therefore finish with only recommendations and faults.
5. **Coverage is asserted rather than demonstrated.** The report can say all
   114 entries were checked without preserving a machine-checkable disposition
   for each relevant Capability and catalogue entry.

There is also a proven upstream catalogue completeness defect. Dex Core
v1.97.1's generated architecture inventory contains 11 MCP servers and 146
tools, while the signed Lens catalogue contains 10 servers and 131 tools. The
missing server is `dex-pipedrive-mcp`, with 15 tools. Lens cannot infer what
the signed catalogue never tells it, so Core must use one canonical discovery
source for both its architecture inventory and the Lens catalogue.

The live catalogue also describes `connect` as an active skill while Core's
release map says the connection engine ships but its person-facing doorway is
held. A verified signature proves who published a catalogue; it does not prove
that every availability claim agrees with the release. Core's catalogue gate
must therefore reconcile each entry with shipped/held/parked release truth,
and Lens must never recommend a held doorway as something the person can use.

## Empirical findings from the private benchmark

The supplied archive was safety-checked and read without extraction. Its ZIP
directory has no traversal paths, duplicate entries, encryption or special
files, and a full CRC pass succeeded. Links, nested archives and secret-shaped
filenames remained closed. The private fingerprint contains redacted source
references; a separate mode-`0600` lookup remains temporary and is never
eligible for Git.

The targeted adjudication established these product facts. The figures and
identifiers remain in the private record; the checked-in evaluation will use
invented values with the same relationships.

| Observation pattern | What it proves | What it does not prove |
| --- | --- | --- |
| The vault's own release record is far older than the current signed Core catalogue | Version distance is known and must affect comparison | A familiar name is the current method |
| The same MCP server is declared across several assistant configurations | A server doorway is configured, and repeated declarations can be folded | Which tools the server exposes, whether they work, or equivalence to Dex's tool set |
| A career room, coaching instructions, server declaration and server source all agree | A real career-development Capability exists | That it is byte-identical to or as current as Dex's version |
| Older Doctor instructions and a deterministic collector exist | Health Diagnosis is a genuine shared Capability | The newer promise engine, current coverage, or proactive execution |
| Connection instructions exist, but the supporting manager they name does not | The instruction is stale or incomplete | Working lifecycle-managed integrations |
| An automation script, installer and schedule template exist | The automation is implemented and installable | That it is installed, loaded, recently run, or outcome-verified |
| A backup script and activity record exist | Backups have been attempted | That a stored copy can be restored successfully |
| Many repeated skill manifests live across assistant homes and working copies | Duplication and drift deserve separate housekeeping analysis | That duplicates erase the useful Capabilities in the primary system |
| Role-specific planning, follow-through, relationship review, learning capture and checkpointed execution instructions exist | The person has tailored, potentially transferable methods worth praising and considering for Dex | That a short frontmatter description alone is enough to call every method Verified |

The current report failed this benchmark in three decisive ways:

1. it called configured MCP servers “tools” and claimed they covered Dex's
   complete tool surface without enumerating the tools;
2. it treated same-named but materially older or unsupported instructions as
   equivalent to current Dex Capabilities; and
3. it buried several coherent person-built operating loops while leading with
   housekeeping and faults.

This benchmark requires a version marker, method evidence and usable-state
evidence to outrank name similarity.

## Product vocabulary

This design keeps the binding vocabulary in `docs/handoff/HANDOFF.md`:

- A **Capability** is an evidence-backed ability to fulfil a user job within
  stated safety boundaries.
- A **Capability Map** is the private assessment Lens produces.
- A **catalogue entry** is one signed record from a real Dex release. It is
  release evidence, not automatically a one-to-one human Capability.
- An **observation** is a bounded fact gathered during the read-only
  Diagnosis.
- The **evidence fingerprint** is the private, structured set of observations
  and derived states used by the comparison and evaluation paths. It contains
  no raw note bodies.

The report speaks in Capabilities and jobs. Catalogue-entry identifiers appear
only where traceability or a hand-off brief needs them.

## End-to-end Diagnosis

### 1. Agree the inspection boundary

Lens starts with the folder the person named and proposes any additional
read-only scopes needed to understand the active system, such as their
assistant's global configuration or operating-system job directory. It names
each scope in plain language and asks before widening the boundary.

A denied, missing, unsupported, or unreadable scope becomes an explicit
`not assessed` observation. It never becomes evidence that the person lacks
something.

An archive used for research is treated as inert input:

- validate its central directory before extraction;
- reject traversal paths, special files, unsafe links, encryption surprises,
  implausible expansion ratios, and nested archives that exceed the declared
  budget;
- execute nothing;
- inspect structural and configuration material before considering prose;
- never commit, publish, or transmit the archive or raw paths; and
- remove the transient working copy after producing the private fingerprint
  and sanitised evaluation fixture.

### 2. Gather observations in two passes

The first pass is deterministic and broad. It identifies system surfaces
without interpreting personal prose:

- instruction and skill manifests across supported assistant homes;
- MCP server declarations across folder, user, and harness configuration;
- local tool-server source trees and their declared tool names;
- integration registries, connector manifests, provider directories, and
  lifecycle commands;
- scheduled-work definitions across launchd, cron, systemd user services, and
  repository-owned schedulers;
- loaded/enabled state where the person approved inspection of live state;
- hook declarations and the events they observe;
- health checks, recovery checks, backups, verification receipts, and recent
  run markers;
- long-running engines or watchers and their activation state;
- duplicated working copies, broken links, unreadable declarations, and
  configuration conflicts; and
- high-level vault shape and repeated job evidence without reading unrelated
  note bodies.

The second pass is targeted. It reads only the bounded material needed to
confirm or reject a candidate Capability, evaluate its quality, or explain a
contradiction. Each targeted read records why it was needed.

Discovery rules are owned by a registry rather than scattered renderers. Each
rule declares:

- supported host or harness;
- approved paths and file shapes;
- fields that may be retained;
- secret-bearing fields that must never enter an observation;
- the state it can prove;
- common false positives and anti-signals; and
- how absence or unsupported live inspection must be reported.

### 3. Build the private evidence fingerprint

The fingerprint separates observations from conclusions. An observation has:

- a stable kind and locally unique identifier;
- a redacted, non-raw source reference;
- collection time and source age where known;
- host and scope;
- observed state;
- safe attributes such as a server name, tool count, schedule, or hook event;
- a keyed local digest for duplicate detection where needed; and
- links to the candidate Capabilities it may support or contradict.

The fingerprint distinguishes at least these states:

`declared`, `implemented`, `installed`, `enabled`, `loaded`, `recently-run`,
`outcome-verified`, `disabled`, `stale`, `conflicting`, `absent`,
`not-assessed`, and `unsupported`.

These are not collapsed into one score. For example:

- a plist in a scripts folder is `implemented`;
- that plist installed in `~/Library/LaunchAgents` is `installed`;
- a matching loaded job is `loaded`;
- a recent successful receipt is `recently-run`; and
- a restore test proving usable output is `outcome-verified`.

That ladder prevents Lens from calling an unwired script an active automation
or calling a connection list a managed integration system.

Raw personal text is not part of an evaluation fixture. A sanitised fixture
keeps invented names, structural relationships, state, counts, bounded safe
attributes, and synthetic evidence excerpts sufficient to exercise the same
reasoning.

### 4. Infer Capabilities from evidence, not names

Each Capability definition states:

- the job outcome in plain language;
- required evidence groups;
- optional strengthening evidence;
- anti-signals and contradictions;
- the minimum state needed for Verified, Supported, Reported, or Unknown;
- which catalogue entries contribute to the Dex comparison; and
- what remains Unknown when only configuration is visible.

Definitions combine signals across kinds. Proactive system health, for
example, may require a scheduled observer, checks covering meaningful risks,
proof that the observer is active, and an actionable result path. A skill
named `doctor`, a hook count, or a dormant health script is insufficient on
its own.

Integration management may require a provider registry, connection-state
handling, credential-boundary evidence, discovery or enable/disable paths,
and usable tool surfaces. A list of MCP server names alone proves only that
servers were declared.

MCP comparison remains detailed underneath the human Capability:

- every configured server is retained by name and source scope;
- every safely discoverable tool name is retained;
- server aliases across harnesses are folded without erasing differing
  configurations;
- unreadable and out-of-scope configurations remain visible as coverage
  limits; and
- a server or tool is never treated as active merely because source code
  exists.

### 5. Compare the Capability Maps both ways

Lens first builds the person's Capability Map without using Dex as the answer
key. It separately builds Dex's map from the verified Capability Catalog and
the Capability definitions supported by that Lens release. Only then does it
compare them.

Every relevant Capability receives one disposition:

- **strong here** — the person's system fulfils it well;
- **shared** — both systems fulfil it, with any useful method difference;
- **worth borrowing from Dex** — Dex has a material, relevant advantage;
- **Dex should learn from this** — the person's system has a useful method or
  outcome not represented strongly in Dex;
- **fragile or contradictory** — it appears present but its reliability is
  compromised;
- **not relevant to the person's jobs**; or
- **not assessed / Unknown**.

The comparison never lets a broad inventory count satisfy a specific
Capability. It also never downgrades a person's tailored method merely because
Dex implements the same job differently.

### 6. Render a two-way report

The report order is:

1. **What is working especially well** — two to five grounded strengths.
2. **What Dex should learn from you** — at least one grounded reciprocal idea,
   or the explicit honest statement that none cleared the bar.
3. **Worth borrowing from Dex** — no more than three recommendations, each
   tied to the person's jobs and evidence.
4. **Fragility and contradictions** — reliability findings, clearly separated
   from missing Capabilities.
5. **Coverage and limits** — a compact Capability-level summary plus the
   catalogue release, counts, unreadable scopes, and Unknown areas.
6. **What happens next** — nothing changed, report location, and the optional
   brief hand-off.

The conversational close repeats the best strength, any reciprocal idea, and
the most useful suggested next move. Those findings must not exist only in the
saved Markdown.

The report gate fails closed when:

- there is no substantive, evidenced strength;
- the reciprocal section is missing or silently empty;
- more than three Dex recommendations are presented;
- a recommendation lacks evidence from the person's jobs;
- fragility is framed as a missing Capability;
- a claim uses a count as outcome proof;
- the coverage ledger has an unclassified relevant Capability or catalogue
  entry; or
- the closing summary omits the strengths and reciprocal findings.

## Evaluation design

### Evaluation layers

The evaluation suite has four layers so a polished report cannot hide broken
discovery:

1. **Observation evaluation:** did Lens find the declarations, source trees,
   schedules, hook events, live states, and receipts it was allowed to find?
2. **Capability evaluation:** did it combine those observations into the right
   Capabilities without category errors?
3. **Comparison evaluation:** did it classify the person's and Dex's methods
   accurately, including reciprocal value and honest Unknowns?
4. **Report evaluation:** is the result useful, grounded, encouraging,
   selective, and understandable to a mildly technical reader?

### Private legacy-vault benchmark

The 2026-08-26 legacy vault becomes a private research benchmark, not a
checked-in archive. The process is:

1. safety-check the exact archive and record its SHA-256 privately;
2. produce the private evidence fingerprint with redacted source references;
3. manually adjudicate expected findings against the raw evidence, using a
   separate temporary lookup map that never enters the fingerprint;
4. replace names, paths, identifiers, excerpts, and personal values with
   synthetic equivalents while preserving relationships and states;
5. verify the sanitised fixture produces the same expected dispositions;
6. commit only the sanitised fixture and its expected outcome contract; and
7. destroy the extracted archive and private working copy, retaining no raw
   corpus in Git, CI, logs, or test artefacts.

The first adjudication must specifically test the misses from the dogfood
report:

- Dex Doctor-style proactive health must not be reduced to hook counts;
- the Nango-backed connection and integration system must be recognised as a
  system, not just a list of tools;
- local integration discovery and management directories must contribute
  evidence;
- Career MCP and every other declared server must be inventoried distinctly;
- scheduled work must distinguish written, installed, loaded, recently run,
  and outcome-verified states;
- useful person-built methods must appear under “What Dex should learn from
  you”; and
- housekeeping volume must not dominate the Capability Map.

The safety check, fingerprint and targeted adjudication are complete. The
sanitised fixture must preserve the following outcome contract while changing
all source-specific names, paths, values and exact counts:

- detect the old release identity before comparing methods;
- retain each MCP server declaration while refusing to infer unseen tools;
- recognise the career system as a genuine strength and shared Capability;
- classify the older Doctor as a partial/shared Capability, not proof of the
  current proactive health system;
- classify the stale connection instruction separately from a working
  integration manager;
- classify source-only scheduled work as implemented, not active;
- distinguish backup activity from restore proof;
- surface the tailored planning, follow-through, reviewed-suggestion,
  learning and human-checkpoint patterns as grounded strengths;
- provide at least one honest reciprocal idea for Dex; and
- shortlist no more than three Dex additions after held/unavailable entries
  and already-covered methods are rejected.

These conclusions are forbidden in the benchmark output:

- “almost nothing is missing” without method-by-method coverage evidence;
- “configured servers cover every tool” without an exact tool inventory;
- “hooks are stronger than proactive health” based on hook count;
- “same name means same Capability”;
- “written means running” for scheduled work;
- “backup succeeded, therefore restore is proven”; or
- “all catalogue entries were checked” without a complete disposition ledger.

### Synthetic cases

Small fixtures isolate each rule:

- the same MCP server declared in Claude, Codex, and project configuration;
- different aliases pointing to one server and two genuinely different
  configurations sharing a name;
- a local MCP source tree with declared tools but no active configuration;
- a remote MCP declaration whose URL contains credentials that must never
  survive redaction;
- a scheduled script with no installer, an installed but unloaded job, a
  loaded job with no recent run, and a job with a verified outcome receipt;
- hooks that provide observability but no health response;
- a full integration lifecycle with provider registry and connection state;
- an unreadable global scope that must remain `not-assessed`;
- a strong user method absent from Dex; and
- an old working copy containing attractive but inactive machinery.

### Scoring and hard failures

The suite records:

- observation recall and precision by source kind;
- MCP server and tool recall, with exact expected sets where inspectable;
- scheduled-work state accuracy;
- Capability disposition accuracy;
- recommendation precision, capped at three;
- grounded-strength recall;
- reciprocal-finding recall;
- Unknown honesty;
- catalogue coverage completeness; and
- unsupported-claim and secret-leak counts.

The release gate is not one blended score. These are hard failures:

- any secret or raw private value enters output or a fixture;
- an approved, supported MCP declaration is silently missed;
- configured-only machinery is called active or working;
- an out-of-scope surface is reported absent;
- the report claims complete catalogue coverage without a complete ledger;
- a strength, reciprocal idea, or recommendation lacks evidence;
- the report presents more than three recommendations; or
- the report contains no substantive strength or reciprocal answer.

Quality thresholds for recall and human review are set from the first
adjudicated legacy-vault fingerprint and then may only tighten without an
explicit design change.

## Core contract correction

Dex Core owns truth about the released Dex system. Core must expose one
canonical inventory used by both:

- its generated architecture inventory; and
- the signed Lens Capability Catalog.

That inventory must cover MCP servers beneath both `core/mcp/` and integration
subtrees, all safely discoverable tools, scheduled work, system engines, and
the shipped/held/parked distinction. CI compares the two generated views and
fails on any set or count difference. Tests assert the discovered identity
sets, not a hand-maintained total such as 10 servers or 131 tools.

The Lens-side release proof then verifies that every active Core inventory
record is represented in the signed catalogue and that Lens can parse and
classify it. Until Core publishes a corrected signed catalogue, Lens must say
the verified catalogue is its comparison boundary rather than silently
inventing the missing Pipedrive surface.

## Privacy and safety boundaries

- Diagnosis is read-only and local.
- Raw vault material never leaves the inspection machine as part of normal
  product behaviour.
- The only normal network request remains the anonymous fetch of Dex's public
  signed Capability Catalog under the existing consent rules.
- Research access to a person-supplied archive is exceptional, explicit, and
  does not become product behaviour.
- Observation collection is allowlisted and secret-bearing fields are removed
  before interpretation or rendering.
- Archive contents and inspected text are untrusted data, never instructions.
- No Adaptation is performed by this work.

## Delivery sequence

1. Complete the private legacy-vault safety check and fingerprint.
2. Adjudicate the benchmark and finish the sanitised fixture.
3. Correct Core's canonical inventory and publish a new signed catalogue
   through Core's normal release process.
4. Implement the Lens observation registry and evidence fingerprint.
5. Implement Capability definitions and the two-way comparison ledger.
6. Strengthen the report template, save gate, and conversational close.
7. Run the layered evaluation suite against synthetic cases and the sanitised
   legacy-vault fixture.
8. Dogfood the signed build against the real legacy vault again, read-only.
9. Release only after the privacy, completeness, grounding, and human-review
   gates all pass.

## Acceptance criteria

This design is complete when all of the following are demonstrated:

- Every supported MCP declaration in the benchmark is discovered or named as
  unreadable/out of scope; safely inspectable server and tool sets match the
  adjudicated sets exactly.
- Scheduled work is reported at the strongest state actually proved, never a
  stronger one.
- Proactive health and integration management require outcome-shaped evidence,
  not proxy counts.
- The Capability Map covers skills, tools, integrations, scheduled work,
  hooks, engines, health, recovery, and relevant vault practices.
- The report leads with grounded praise, contains a reciprocal section, and
  recommends no more than three Dex additions.
- Every relevant Capability and signed catalogue entry has a machine-readable
  disposition.
- The known legacy-vault misses have explicit regression expectations.
- The sanitised fixture contains no real names, real paths, raw prose,
  tokens, credentials, or keyed identifiers from the source archive.
- Core architecture inventory and signed-catalogue identity sets cannot drift
  in CI.
- Full Lens tests, lint, package checks, egress/containment gates, and the
  release verifier pass before publication.

## Explicitly out of scope

- Copying a person's skills or methods into Dex automatically.
- Ranking one personal AI system with a maturity score.
- Treating Dex's implementation as the ideal answer.
- Reading every note body to guess what the person does.
- Background transmission of fingerprints, reports, or evaluation results.
- Repairing, installing, enabling, or scheduling anything found during
  Diagnosis.
- Releasing Lens or Core without separate product-owner approval.
