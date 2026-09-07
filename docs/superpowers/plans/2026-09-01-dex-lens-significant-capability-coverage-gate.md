# Dex Lens Significant Capability Coverage Gate Implementation Plan

> **Status:** Approved by Dave on 1 September 2026. Implementation may proceed
> through linked draft PRs. Merge, release, signing, catalogue publication and
> production deployment still require separate approval.

**Goal:** Make a Dex Lens diagnosis mechanically account for every signed Dex
capability, every exact MCP tool, and every safe local observation while
explaining significant end-to-end systems in plain language and retaining
grounded praise for methods Dex should learn from.

**Architecture:** Extend the existing deterministic diagnosis engine rather
than replacing it. Dex Core remains the signed source of what Dex contains and
how it is grouped. Lens owns read-only detection, evidence state, comparison,
reporting, and the five-tool MCP workflow. The language model may propose
semantic mappings and write explanatory prose; it may not change the checklist,
evidence, counts, availability, dispositions, or close state.

**Current source truth:** Lens `origin/main` at `52183246`; Core
`upstream/main` at `1e73611a`; released Core truth remains v1.97.6. Current Core
source discovers 115 catalogue entries, 11 MCP servers and 151 exact MCP tools,
including `dex-work-mcp` with 50 tools and `dex-career-mcp` with 8 tools.

---

## Non-negotiable invariants

1. Every signed catalogue capability appears exactly once in the comparison
   ledger and exactly once in the canonical report appendix.
2. Every exact tool published for an MCP server is retained under that server;
   examples never substitute for the complete tool list.
3. Every safe local observation receives a disposition. Unmatched observations
   are never discarded; they are candidates for grounded praise or an honest
   `not-assessed` result.
4. Configuration, runtime and health are separate evidence axes. A file can
   prove configuration, but never by itself prove that a service is running or
   healthy.
5. Provider type identity is retained. Account names, workspace names, tokens,
   commands and other private values are not retained.
6. Family availability is derived from member capability availability. A
   family cannot upgrade a dormant or parked member.
7. Held and parked work may be explained but cannot be recommended as
   currently usable.
8. Diagnosis stays read-only. Repair, installation, sharing and publication
   remain separate approved flows.
9. The current five MCP tools remain thin adapters over the engine; no second
   checklist or orchestration path is introduced.
10. Old family-free catalogues remain verifiable during the transition.

## Equality gates

```text
signed_catalogue_ids == comparison_ledger_catalogue_ids
signed_catalogue_ids == rendered_appendix_catalogue_ids
fingerprint_observation_ids == comparison_ledger_local_ids
fingerprint_observation_ids == rendered_appendix_local_ids
discovered_mcp_servers == emitted_mcp_servers
discovered_mcp_tools_by_server == emitted_mcp_tools_by_server
```

## Significant capability families

The first signed family registry covers these reviewed outcome loops. Detailed
leaf capabilities remain visible beneath them.

1. `meeting-follow-through` — meetings become notes, people context and tracked
   follow-up.
2. `living-people-company-context` — people and company pages are created,
   refreshed and connected over time.
3. `durable-task-continuity` — tasks can be captured from several places and
   completion returns to linked surfaces.
4. `external-task-interoperability` — Todoist, Things and Trello can exchange
   tasks on request without pretending background polling exists.
5. `connected-work-context` — Google, Teams, Zoom, Atlassian and Apple Mail can
   inform plans, preparation and reviews when explicitly connected.
6. `pipedrive-pipeline-continuity` — live pipeline context informs local work;
   external writes stay previewed and confirmed.
7. `daily-weekly-operating-rhythm` — planning, review and reflection form one
   repeatable operating cadence.
8. `durable-work-memory` — sourced decisions, commitments, context and patterns
   remain available across sessions.
9. `proactive-health-and-recovery` — Doctor and scheduled checks distinguish
   healthy, off, broken and unknown, then use bounded repair paths.
10. `backup-and-restore-confidence` — backups are created and recovery is
    proved by a safe restore rehearsal.
11. `safe-change-and-rewind` — changes are previewed, verified, receipted and
    reversible.
12. `capability-discovery-and-adoption` — useful methods can be discovered,
    reviewed, adopted and created through the safe lifecycle.
13. `privacy-safe-feedback-loop` — a problem can become a minimal report and a
    returned answer or fix without exporting private work.
14. `career-growth-evidence` — Career and Resume tools turn consented evidence
    into development and application support without inventing claims.

The connection-manager provider directory is represented as shipped groundwork
with its exact status. It does not make the held `/connect` doorway available.
The Nango directory is referenced by provider type and pinned package identity;
it is not expanded into hundreds of falsely active Dex capabilities.

---

## Workstream A — Lens accepts and verifies complete signed truth

### Task 1: Extend the backwards-compatible catalogue contract

**Files:**

- Modify `src/capability_exchange/catalogue/v2.py`
- Modify `src/capability_exchange/catalogue/schema_contract.py`
- Modify `scripts/export_catalogue_schema.py`
- Modify generated files under `schemas/`
- Add catalogue contract tests
- Modify `src/capability_exchange/boundary/data_inventory.yaml`

**Test first:** prove current family-free catalogue bytes still validate; prove
closed family models, aliases, typed components, detector profile/manual-only
rules and complete MCP tool inventories fail before implementation.

For MCP entries add a backwards-compatible sampled/complete inventory contract.
`complete` requires `tool_count == len(tools)`, unique tool names, and every
example to be a member of the complete list. Sampled entries remain valid but
cannot satisfy the new release gate.

For families add exact member capability IDs, aliases, typed components and an
assessment contract. Typed components may reference a capability, exact MCP
tool, Nango provider type or reviewed source component. No component stores a
second availability value.

### Task 2: Derive family state from leaf truth

**Files:**

- Create `src/capability_exchange/diagnosis/families.py`
- Add `tests/diagnosis/test_capability_family_delta.py`
- Modify `src/capability_exchange/catalogue/agent.py`

Derive `available`, `partial` and `unavailable` solely from signed member
entries. Prove parked members cannot enter recommendation candidates. Keep the
three-recommendation limit.

---

## Workstream B — Lens closes the comparison in both directions

### Task 3: Give every local observation a disposition

**Files:**

- Modify `src/capability_exchange/diagnosis/comparison.py`
- Modify `src/capability_exchange/diagnosis/defaults.py`
- Modify `src/capability_exchange/diagnosis/specialists.py`
- Modify `src/capability_exchange/boundary/data_inventory.yaml`
- Add focused comparison/default/specialist tests

Add a closed local-observation ledger entry. Production construction must take
the exact verified catalogue and fingerprint, seed every local observation as
`not-assessed`, and apply only proposals that cite known observation and
evidence IDs. Omission, duplication or an unknown reference fails closed.

### Task 4: Separate configured, running and healthy

**Files:**

- Modify `src/capability_exchange/diagnosis/observations.py`
- Modify `src/capability_exchange/adapters/claude_code/discovery.py`
- Modify `src/capability_exchange/adapters/claude_code/live_state.py`
- Modify `src/capability_exchange/diagnosis/run.py`
- Add read-only stored-run upgrade tests

Replace the single operational scalar in the new run schema with three closed
axes. Old stored runs are read through one explicit upgrade; the new schema
does not emit two competing truths. Live host state is collected only when the
approved scope receipt includes it.

### Task 5: Preserve safe provider identities

**Files:**

- Modify `src/capability_exchange/adapters/claude_code/discovery.py`
- Add provider discovery privacy tests

Emit one observation per safe provider type. Derive aggregate counts later.
Reject secret-shaped keys and never retain account/workspace labels, commands,
URLs or credentials.

### Task 6: Render the complete canonical appendix

**Files:**

- Modify `src/capability_exchange/diagnosis/report.py`
- Modify `src/capability_exchange/diagnosis/orchestrator.py`
- Modify `src/capability_exchange/reports/store.py`
- Add report, orchestrator, store and replay tests

The stored report must contain, in stable order, every catalogue disposition,
every exact MCP tool under its server and every local observation with all
three evidence axes. The report checker rejects a missing, duplicated,
reordered or contradictory appendix. The readable summary may stay short and
recommend at most three ideas.

### Task 7: Keep MCP progress typed and engine-owned

**Files:**

- Modify `src/capability_exchange/diagnosis/run.py`
- Modify `src/capability_exchange/diagnosis/mcp_server.py`
- Modify `tests/diagnosis/test_mcp_server.py`

Keep the five existing read-only tools. Return a typed required step instead of
making the adapter parse error strings. Prove direct-engine and MCP results are
byte-identical and include the same ledger/appendix identity.

### Task 8: Generate the packaged fallback

**Files:**

- Create `scripts/generate_capability_reference.py`
- Regenerate `src/capability_exchange/skill/dex-lens/dex-capabilities.json`
- Modify fallback, installer and packaging tests
- Modify the Dex Lens skill instructions

Generate the fallback from a signature-verified catalogue. Never merge fallback
facts into a current enriched signed catalogue. The skill asks the engine for
status/result and does not maintain a parallel manual checklist.

---

## Workstream C — Core publishes reviewed significant-capability truth

### Task 9: Add one canonical significant-capability registry

**Files:**

- Create `core/lens-catalog/significant-capabilities.json`
- Create `core/lens_significant_capabilities.py`
- Add `core/tests/test_lens_significant_capabilities.py`

The registry owns aliases, the 14 family definitions, exact leaf membership,
typed components and reviewed provider references. It cannot store
availability. Closed validation rejects stale IDs, duplicate aliases, unknown
components, unrecognised assessment profiles and unsafe text.

### Task 10: Publish every exact MCP tool

**Files:**

- Modify `scripts/generate-dex-lens-catalog.py`
- Modify Core discovery/generator tests

Emit the exact ordered tool tuple already found by canonical discovery. Assert
server-set and per-server tool-set equality. Add explicit regression assertions
for Work (50 tools on current main) and Career (8), while deriving release
counts rather than hard-coding them in production.

### Task 11: Validate provider references without overstating availability

**Files:**

- Add a small repository-owned provider identity exporter if needed
- Modify significant-capability validation tests
- Modify release-path trigger tests

Every referenced provider ID must exist in pinned `@nangohq/providers` 0.70.5.
Provider presence, Dex support and security-vetted status remain separate
facts. Missing dependencies fail honestly; release CI installs the pinned data
source before the check.

### Task 12: Add the Core release coverage gate

**Files:**

- Modify `scripts/lens-catalog-release-path.py`
- Modify `.github/workflows/ci.yml`
- Modify generator/release-truth tests

Fail publication for discovered-versus-emitted MCP drift, unknown aliases or
components, missing significant-family coverage, provider identity loss,
status drift, schema drift or generated-preview drift. Active core/high leaves
must belong to a family or carry a reviewed exception with a plain-language
reason.

### Task 13: Vendor only an exact released Lens contract

Core may use a proposal fixture for tests on its guarded preview branch, but
the production generator and signer remain blocked. Only after Dave approves
Lens merge/release may Core vendor the exact tagged schema bytes and checksum,
regenerate the preview and enable the production path.

---

## Workstream D — evaluation and delivery

### Task 14: Add sanitised realistic evaluations

Use invented fixtures derived from the failure patterns in Dave's test vault.
Never commit the vault archive, transcript, names, private paths or excerpts.

Fixtures cover present, partial, misleading and absent cases for every claimed
platform profile. They must prove:

- all 14 families receive a disposition;
- Doctor, proactive health, integration/provider systems, people/company
  maintenance, task creation and continuity are not omitted;
- Work, Career, Resume and Session Memory are visible;
- unmatched local MCP servers and workflows become grounded strengths or
  `not-assessed`, never disappear;
- the first three recommendations stay bounded and useful;
- held/parked Dex work is not offered as available.

### Task 15: Verify and hand off without publishing

Run focused tests during each task, then full Lens tests/Ruff and the full Core
non-fuzz Python suite plus relevant Node/integration, schema, generated-file and
architecture-inventory gates. Perform independent review of each diff.

Push linked branches and open Lens then Core draft PRs. The Core PR states its
dependency on an exact tagged Lens contract. Reconcile Mission Control and
Dispatch if their mounted helpers become available. Do not merge, release,
sign, publish, deploy or change the live catalogue in this implementation
stage.

## Completion boundary for this approved build

The current build is ready for Dave's release decision when:

1. Lens's backwards-compatible contract and deterministic engine changes are
   implemented, tested, pushed and in a draft PR;
2. Core's registry, complete MCP inventory and guarded preview gates are
   implemented, tested, pushed and in a linked draft PR;
3. sanitised evaluations prove complete catalogue/local accounting and the
   expected human experience;
4. both diffs pass independent review; and
5. production signing/publication remains mechanically blocked until a tagged
   Lens release is vendored by exact bytes.
