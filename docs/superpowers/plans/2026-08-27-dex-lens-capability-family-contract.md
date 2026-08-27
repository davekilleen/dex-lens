# Dex Lens Capability Family Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add signed, release-truth capability families so Lens can explain
material Dex systems and version distance in plain language without hiding
detail or presenting held work as available.

**Architecture:** Lens first releases a backwards-compatible verifier that
accepts an optional closed `capability_families` collection and derives family
availability from the existing member entries. Core then vendors that exact
tagged schema and publishes the next signed catalogue with curated family
membership; Lens's deterministic report engine renders family deltas while
retaining every detailed catalogue disposition underneath.

**Tech Stack:** Python 3.11+, Pydantic v2, JSON Schema Draft 2020-12,
Ed25519 catalogue signatures, Core's catalogue generator, pytest, Ruff

---

## Delivery boundaries

- This plan is sequenced after Tasks 1–8 of
  `2026-08-27-dex-lens-deterministic-diagnosis-engine.md`, because the report
  family view consumes its typed `ReportModel`.
- Lens must release the complete verifier contract before Core signs catalogue
  bytes containing the new field. A proposal fixture is never used as release
  authority.
- The family layer is additive. Older signed catalogues with no families
  continue to verify and simply omit the version-family section.
- Member-entry availability remains authoritative. A family cannot upgrade a
  dormant skill or parked engine to active.
- No plan step merges, releases, signs or promotes the public catalogue without
  Dave's later explicit approval.

## File map

### Dex Lens

- Modify: `src/capability_exchange/catalogue/v2.py`
- Modify: `src/capability_exchange/catalogue/schema_contract.py`
- Modify: `src/capability_exchange/catalogue/agent.py`
- Modify: `src/capability_exchange/diagnosis/report.py`
- Create: `src/capability_exchange/diagnosis/families.py`
- Create: `tests/catalogue/test_capability_families.py`
- Create: `tests/diagnosis/test_capability_family_delta.py`
- Modify: `tests/catalogue/test_enriched_contract.py`
- Modify: `tests/catalogue/test_v2_verifier.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`

### Dex Core

- Create: `core/lens-catalog/families.json`
- Modify: `scripts/generate-dex-lens-catalog.py`
- Modify: `core/tests/test_dex_lens_catalog_generation.py`
- Modify: `core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json`
- Modify: `docs/examples/dex-lens-catalog-enriched-preview.json`
- Modify: `docs/dex-lens-catalogue-enriched-schema-delta.md`
- Modify: `CHANGELOG.md`

## Workstream A — Lens owns the next complete contract first

### Task 1: Add a backwards-compatible family schema to Lens

**Files:**
- Modify: `src/capability_exchange/catalogue/v2.py`
- Create: `tests/catalogue/test_capability_families.py`
- Modify: `tests/catalogue/test_v2_verifier.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`

- [ ] **Step 1: Write failing old/new catalogue compatibility tests**

```python
def test_catalogue_without_families_remains_valid(enriched_catalogue: CatalogueV2) -> None:
    assert enriched_catalogue.capability_families == ()


def test_family_members_must_be_exact_catalogue_ids(enriched_payload: dict) -> None:
    enriched_payload["catalogue"]["capability_families"] = [
        family(member_ids=["missing-capability"])
    ]
    with pytest.raises(ValidationError, match="unknown member capability"):
        SignedCatalogueEnvelopeV2.model_validate(enriched_payload)
```

Add tests for duplicate family IDs, duplicate member IDs, empty membership,
unknown jobs, control characters and extra fields.

- [ ] **Step 2: Run the family tests red**

Run:

```bash
.venv/bin/python -m pytest tests/catalogue/test_capability_families.py -q
```

Expected: FAIL because `CatalogueV2` rejects the new field.

- [ ] **Step 3: Add the closed family model**

Implement:

```python
class CapabilityFamilyV2(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family_id: str = Field(pattern=_ID_RE.pattern)
    title: str = Field(min_length=1, max_length=140)
    outcome: str = Field(min_length=1, max_length=800)
    jobs: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=20, json_schema_extra={"uniqueItems": True}
    )
    member_capability_ids: tuple[_CatalogueId, ...] = Field(
        min_length=1, max_length=80, json_schema_extra={"uniqueItems": True}
    )

    _jobs_unique = field_validator("jobs")(_job_ids_are_unique_catalogue_ids)


class CatalogueV2(InventoriedModel):
    jobs_taxonomy: tuple[JobTaxonomyEntryV2, ...]
    capabilities: tuple[CatalogueCapabilityEntryV2, ...]
    capability_families: tuple[CapabilityFamilyV2, ...] = Field(
        default=(), max_length=40,
        json_schema_extra={"uniqueItems": True, UNIQUE_BY_KEYWORD: "family_id"},
    )
    portable_brief: PortableBriefContractV2
```

Extend `_cross_references_are_closed` so family jobs and member identities are
subsets of the exact catalogue sets.

- [ ] **Step 4: Prove availability is never stored on the family**

Assert the exported schema has no family `availability` property. The report
layer must derive it from `capability_availability_of()` for current member
entries; this prevents a second status from drifting from release truth.

- [ ] **Step 5: Pass compatibility tests and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/catalogue/test_capability_families.py \
  tests/catalogue/test_enriched_contract.py \
  tests/catalogue/test_v2_verifier.py -q
```

Expected: PASS for both the current family-free signed catalogue and the new
synthetic family catalogue.

```bash
git add src/capability_exchange/catalogue/v2.py \
  src/capability_exchange/boundary/data_inventory.yaml \
  tests/catalogue/test_capability_families.py \
  tests/catalogue/test_v2_verifier.py
git commit -m "feat: accept signed capability families"
```

### Task 2: Export and freeze the exact Lens family schema

**Files:**
- Modify: `src/capability_exchange/catalogue/schema_contract.py`
- Modify: `tests/catalogue/test_enriched_contract.py`
- Modify: `docs/STATUS.md`

- [ ] **Step 1: Add an exact exported-schema test**

```python
def test_exported_schema_contains_closed_capability_families() -> None:
    schema = build_catalogue_schema()
    catalogue = schema["$defs"]["CatalogueV2"]
    assert "capability_families" in catalogue["properties"]
    family = schema["$defs"]["CapabilityFamilyV2"]
    assert family["additionalProperties"] is False
    assert set(family["required"]) == {
        "family_id",
        "title",
        "outcome",
        "jobs",
        "member_capability_ids",
    }
```

- [ ] **Step 2: Run the schema export test red**

Run:

```bash
.venv/bin/python -m pytest \
  tests/catalogue/test_enriched_contract.py::test_exported_schema_contains_closed_capability_families -q
```

Expected: FAIL before regenerating the export.

- [ ] **Step 3: Export both canonical schema artifacts**

Run the repository-owned schema exporter, then validate its output with the
runtime `build_catalogue_schema()` and `iter_catalogue_schema_errors` paths.
Do not hand-edit exported JSON.

- [ ] **Step 4: Record release truth**

`docs/STATUS.md` must say: contract implemented and locally verified; Core
publication held until this exact Lens schema is reviewed, merged and released.

- [ ] **Step 5: Pass export drift checks and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/catalogue/test_enriched_contract.py \
  tests/catalogue/test_v2_verifier.py -q
git diff --check
```

Expected: PASS and clean generated-schema drift.

```bash
git add src/capability_exchange/catalogue/schema_contract.py \
  schemas/dex-lens-catalogue-v2.schema.json \
  schemas/dex-lens-catalogue-v2-dialect.schema.json \
  docs/STATUS.md tests/catalogue/test_enriched_contract.py
git commit -m "build: export Lens capability family contract"
```

### Task 3: Render family availability and version delta from member truth

**Files:**
- Create: `src/capability_exchange/diagnosis/families.py`
- Create: `tests/diagnosis/test_capability_family_delta.py`
- Modify: `src/capability_exchange/diagnosis/report.py`
- Modify: `src/capability_exchange/catalogue/agent.py`

- [ ] **Step 1: Write failing derived-family tests**

```python
def test_family_state_is_partial_when_only_some_members_are_active() -> None:
    summary = summarise_family(
        family=family(member_ids=("active-entry", "parked-entry")),
        entries=(active_engine("active-entry"), parked_engine("parked-entry")),
    )
    assert summary.availability is FamilyAvailability.PARTIAL
    assert summary.available_member_ids == ("active-entry",)
    assert summary.unavailable_member_ids == ("parked-entry",)


def test_parked_member_is_explained_but_never_recommended() -> None:
    delta = build_family_delta(
        current_version="1.97.2",
        inspected_version="1.18.1",
        family=connection_family(),
        entries=connection_entries(),
    )
    assert "not currently available" in delta.plain_language_state
    assert delta.recommendable_member_ids == ()
```

- [ ] **Step 2: Run family-delta tests red**

Run:

```bash
.venv/bin/python -m pytest tests/diagnosis/test_capability_family_delta.py -q
```

Expected: FAIL because family summaries do not exist.

- [ ] **Step 3: Implement derived family summaries**

Use `FamilyAvailability` values `available`, `partial`, `unavailable`.
Availability and recommendation IDs are calculated solely from current member
entries and `capability_is_active()`. A family whose members have no
`since_release` evidence may be described but not placed in the version delta.

- [ ] **Step 4: Add the report sections**

When lineage and version are proven, render “What has changed since your
version” before immediate recommendations. Always keep at most three immediate
recommendations. Put other applicable families under “Worth exploring later”
without presenting them as gaps or calls to install.

- [ ] **Step 5: Pass tests and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/diagnosis/test_capability_family_delta.py \
  tests/diagnosis/test_report_model.py \
  tests/catalogue/test_agent_surface.py -q
```

Expected: PASS.

```bash
git add src/capability_exchange/diagnosis/families.py \
  src/capability_exchange/diagnosis/report.py \
  src/capability_exchange/catalogue/agent.py \
  tests/diagnosis/test_capability_family_delta.py
git commit -m "feat: explain Dex capability families by release truth"
```

## Workstream B — Core publishes curated family truth

### Task 4: Add the canonical Core family registry

**Files:**
- Create: `core/lens-catalog/families.json`
- Modify: `scripts/generate-dex-lens-catalog.py`
- Modify: `core/tests/test_dex_lens_catalog_generation.py`

- [ ] **Step 1: Write failing registry-validation tests**

```python
def test_family_registry_members_are_exact_generated_capability_ids(tmp_path: Path) -> None:
    data = family_registry()
    data["families"][0]["member_capability_ids"].append("missing-capability")
    result = generate_with_family_registry(tmp_path, data)
    assert result.returncode == 1
    assert "unknown member capability" in result.stderr


def test_featured_modern_system_entries_have_a_family(tmp_path: Path) -> None:
    catalogue = generated_catalogue(tmp_path)
    family_members = {
        item for family in catalogue["capability_families"]
        for item in family["member_capability_ids"]
    }
    required = {
        "dex-doctor",
        "proactive-health-engine",
        "dex-update",
        "dex-customization-carryover-mcp",
        "process-meetings",
        "relationship-memory-pages",
        "tasks-single-source-of-truth",
        "todoist-setup",
        "things-setup",
        "trello-setup",
        "diff-generate",
        "diff-adopt",
    }
    assert required <= family_members
```

- [ ] **Step 2: Run generator tests red**

Run:

```bash
python3 -m pytest \
  core/tests/test_dex_lens_catalog_generation.py -k family -q
```

Expected: FAIL because Core has no family registry or generator support.

- [ ] **Step 3: Create the first curated family set**

Create these exact family IDs and plain-language outcomes:

```json
{
  "registry_version": 1,
  "families": [
    {
      "family_id": "system-health-and-recovery",
      "title": "Dex watches its own health",
      "outcome": "Dex checks whether important background work is succeeding, explains failures, and proves recovery paths rather than trusting that a job merely started."
    },
    {
      "family_id": "connected-tools-lifecycle",
      "title": "Connected tools stay connected",
      "outcome": "Dex discovers supported tools, keeps connection state understandable, and distinguishes an available connection route from groundwork that is still held."
    },
    {
      "family_id": "safe-updates-and-rewind",
      "title": "Safe updates you can rewind",
      "outcome": "Dex previews change, preserves personal customisation, verifies the result, and can recover without writing over the live system blindly."
    },
    {
      "family_id": "living-people-context",
      "title": "People context stays alive",
      "outcome": "Meetings, relationship history, open actions and changing contact patterns stay connected so the person does not walk into important conversations cold."
    },
    {
      "family_id": "two-way-task-continuity",
      "title": "Tasks stay in sync",
      "outcome": "One task truth stays linked to people, companies, projects and external task tools, with review when ownership or status is uncertain."
    },
    {
      "family_id": "share-and-adopt-methods",
      "title": "Share and adopt ways of working",
      "outcome": "A useful workflow can be explained, reviewed, adapted and removed without copying somebody else's private system wholesale."
    }
  ]
}
```

Add `jobs` and curated `member_capability_ids` to every object using exact IDs
from the generated current catalogue. The exact twelve feature-story IDs in
the test above must be covered, together with the other entries whose reviewed
methods genuinely contribute to those six systems. Other catalogue entries
remain detailed capabilities and canonical-job members; this feature-story
layer does not force unrelated career, writing or project capabilities into a
misleading family. Do not include an ID solely because its name sounds
related: inspect its annotation and release availability first.

- [ ] **Step 4: Extend the generator with closed validation**

Load the family registry after all four classes have been discovered. Require
exact fields, unique IDs, unique members, known canonical jobs, known generated
member IDs, safe bounded text and at least one member. Emit families sorted by
registry order and member IDs in declared order. Never infer availability at
generation time.

- [ ] **Step 5: Pass focused generator tests and commit**

Run:

```bash
python3 -m pytest \
  core/tests/test_dex_lens_catalog_generation.py -k 'family or enriched' -q
python3 scripts/generate-dex-lens-catalog.py --enriched-preview \
  --output /tmp/dex-lens-family-preview.json
python3 -m json.tool /tmp/dex-lens-family-preview.json >/dev/null
```

Expected: PASS and valid JSON.

```bash
git add core/lens-catalog/families.json \
  scripts/generate-dex-lens-catalog.py \
  core/tests/test_dex_lens_catalog_generation.py
git commit -m "feat: publish canonical Dex capability families"
```

### Task 5: Vendor the exact released Lens schema before signing Core bytes

**Files:**
- Modify: `core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json`
- Modify: `core/tests/test_dex_lens_catalog_generation.py`
- Modify: `docs/examples/dex-lens-catalog-enriched-preview.json`
- Modify: `docs/dex-lens-catalogue-enriched-schema-delta.md`

- [ ] **Step 1: Record the released Lens tag and schema checksum**

Download the schema from the exact Lens release tag approved for this
contract. Verify its SHA-256 against the release record and copy those exact
bytes into Core. A branch fixture or working-tree export is refused.

- [ ] **Step 2: Add exact byte-identity and version-floor tests**

Assert Core's vendored bytes match the downloaded tag artifact, the schema
root declares the required Lens minimum version, and the current released
family-free Core catalogue still validates.

- [ ] **Step 3: Generate the family catalogue against the released schema**

Run the default generator and its internal schema validation, then the family
preview and its internal validation. Compare the committed example with exact
generated output.

- [ ] **Step 4: Prove held truth**

Assert every member entry retains its actual availability. In particular, a
held connection doorway or parked engine may appear as an unavailable family
member but cannot enter the active recommendation set.

- [ ] **Step 5: Pass focused checks and commit**

Run:

```bash
python3 -m pytest \
  core/tests/test_dex_lens_catalog_generation.py \
  core/tests/test_lens_catalog_discovery.py \
  core/tests/test_lens_catalog_enriched_discovery.py -q
python3 -m json.tool docs/examples/dex-lens-catalog-enriched-preview.json >/dev/null
```

Expected: PASS and exact generated-example equality.

```bash
git add core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json \
  core/tests/test_dex_lens_catalog_generation.py \
  docs/examples/dex-lens-catalog-enriched-preview.json \
  docs/dex-lens-catalogue-enriched-schema-delta.md
git commit -m "build: vendor released Lens family contract"
```

## Workstream C — prove the intended human experience

### Task 6: Add the modern-system family evaluation

**Files:**
- Modify: `tests/evals/real_session_fixture.py`
- Create: `tests/evals/test_modern_dex_family_story.py`
- Modify: `tests/fixtures/evals/real-session-expected.json`

- [ ] **Step 1: Add synthetic version-distance expectations**

The invented older system must trigger all six family headings while retaining
the detailed entries underneath. Include one unavailable family whose members
are all held/parked and one partial family with both active and unavailable
members.

- [ ] **Step 2: Add the human-story assertions**

```python
def test_version_delta_surfaces_modern_dex_systems_without_sales_copy() -> None:
    report = render_real_session_family_report()
    assert "Dex watches its own health" in report
    assert "Connected tools stay connected" in report
    assert "Safe updates you can rewind" in report
    assert "People context stays alive" in report
    assert "Tasks stay in sync" in report
    assert "Share and adopt ways of working" in report
    assert "now does" not in report.lower()
    assert "parked and dormant" not in report.lower()
```

Add assertions that technical terms are followed by one plain-language
explanation and no family creates a fourth recommendation.

- [ ] **Step 3: Run the family-story evaluation red, then green**

Run before wiring the family report: expect FAIL. Wire the exact signed family
models into `ReportModel`, rerun and expect PASS.

- [ ] **Step 4: Run both full repository suites**

Lens:

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check src tests
```

Core:

```bash
python3 -m pytest core/tests/ core/mcp/tests/ core/migrations/tests/ \
  -m "not fuzz" -q
python3 -m ruff check core scripts
```

Expected: PASS; record exact counts and every environment-gated skip.

- [ ] **Step 5: Push two review branches and open linked draft PRs**

Open the Lens contract/report PR first. The Core PR must remain draft and
explicitly blocked on an exact released Lens tag. Link both to the same
Mission Control card and the deterministic-engine design. Do not merge, sign,
release or change the live catalogue.

## Final completion proof

This plan is complete only when:

1. Lens verifies both old family-free catalogues and the new closed family
   contract;
2. Core emits family membership from one reviewed registry into bytes that
   validate against the exact released Lens schema;
3. the exact featured modern-system entries have a family while unrelated
   catalogue entries and all detailed identities remain unchanged;
4. family availability is derived from member entries and cannot drift;
5. held/parked members are explained but never recommended;
6. version distance produces the six intended plain-language system stories;
7. the report still recommends at most three immediate additions and leads
   with grounded strengths and reciprocal value;
8. both repository suites, lint, schema drift and exact-example checks pass;
9. the linked draft PRs and Mission Control evidence state are coherent; and
10. no public catalogue or Lens release is published without Dave's later
    explicit approval.
