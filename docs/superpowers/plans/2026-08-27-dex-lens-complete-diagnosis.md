# Dex Lens Complete Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Dex Lens discover a personal AI system as a working whole, compare it truthfully with Dex's complete released surface, and produce a selective two-way report that praises strong work, captures ideas Dex should learn, and recommends at most three useful additions.

**Architecture:** Core first produces one complete, release-truthful signed Capability Catalog from canonical repository discovery. Lens then turns explicitly approved read-only scopes into a closed, secret-safe evidence fingerprint, uses a complete comparison ledger to account for every catalogue entry, and refuses thin or one-way reports. A synthetic legacy-vault evaluation preserves the failure relationships found during private dogfooding without retaining real names, paths, prose, identifiers, or exact counts.

**Tech Stack:** Python 3.13, Pydantic v2, JSON/TOML/plist parsing from the standard library, pytest, Ruff, Ed25519 catalogue verification, Markdown report gates, GitHub Actions.

---

## Delivery boundaries

- Execute Core and Lens changes in separate clean Treehouse worktrees.
- Land the Core truth correction before Lens consumes a replacement catalogue.
- Do not copy the private archive or fingerprint into either repository.
- Do not publish a Core catalogue, Lens package, installer, website change, or release without separate product-owner approval.
- The normal Lens network boundary remains one anonymous fetch of the public signed catalogue. No fingerprint, ledger, report, or evaluation result leaves the person's machine.
- The existing eight Foundation Capabilities and R2 Evidence State vocabulary remain unchanged. Operational state is a new, separate axis.

## Workstream A — Core catalogue completeness and release truth

### Task 1: Make MCP discovery canonical

**Repository:** Dex Core

**Files:**
- Modify: `core/lens_catalog_discovery.py`
- Modify: `scripts/generate-architecture-inventory.py`
- Modify: `core/tests/test_lens_catalog_enriched_discovery.py`
- Modify: `core/tests/test_architecture_inventory.py`

- [ ] **Step 1: Change the Lens discovery expectation from the stale count to the exact repository set**

Replace the count-only assertion with identity and tool-set assertions:

```python
def test_discovers_every_core_and_integration_mcp_server() -> None:
    servers = discover_mcp_servers(REPO_ROOT)

    assert {server.server_name for server in servers} == {
        "dex-analytics",
        "dex-calendar-mcp",
        "dex-career-mcp",
        "dex-google-workspace-mcp",
        "dex-granola-mcp",
        "dex-improvements-mcp",
        "dex-meeting-intelligence",
        "dex-onboarding-mcp",
        "dex-resume-mcp",
        "dex-work-mcp",
        "dex-pipedrive-mcp",
    }
    assert sum(server.tool_count for server in servers) == 146
    pipedrive = next(server for server in servers if server.server_name == "dex-pipedrive-mcp")
    assert pipedrive.source_path == "core/integrations/pipedrive/pipedrive_server.py"
    assert pipedrive.tool_count == 15
```

- [ ] **Step 2: Run the focused test and prove the current source boundary is incomplete**

Run:

```bash
python3 -m pytest core/tests/test_lens_catalog_enriched_discovery.py::test_discovers_every_core_and_integration_mcp_server -q
```

Expected: FAIL because `dex-pipedrive-mcp` is absent and the discovered total is 131 tools.

- [ ] **Step 3: Put the complete source boundary in `discover_mcp_servers`**

Add one canonical path function and use it inside the existing parser:

```python
MCP_SERVER_GLOBS: tuple[str, ...] = (
    "core/mcp/*_server.py",
    "core/integrations/*/*_server.py",
)


def mcp_server_sources(release_root: Path) -> tuple[Path, ...]:
    root = release_root.resolve(strict=True)
    sources = {
        path
        for pattern in MCP_SERVER_GLOBS
        for path in root.glob(pattern)
        if path.is_file()
    }
    return tuple(sorted(sources, key=lambda path: path.relative_to(root).as_posix()))


def discover_mcp_servers(release_root: Path) -> tuple[McpServerCandidate, ...]:
    root = release_root.resolve(strict=True)
    candidates = [
        discover_mcp_server_source(root, path)
        for path in mcp_server_sources(root)
    ]
    return tuple(sorted(candidates, key=lambda item: (item.server_name, item.source_path)))
```

- [ ] **Step 4: Remove the second source-boundary implementation from the architecture generator**

Import `discover_mcp_servers` and map those records directly:

```python
from core.lens_catalog_discovery import LensDiscoveryError, discover_mcp_servers


def discover_engines(repo_root: Path) -> list[Engine]:
    try:
        candidates = discover_mcp_servers(repo_root)
    except LensDiscoveryError as error:
        raise InventoryError(str(error)) from error
    return [
        Engine(
            source=candidate.source_path,
            server_name=candidate.server_name,
            tools=candidate.tools,
            has_feature_status=candidate.has_feature_status,
        )
        for candidate in candidates
    ]
```

- [ ] **Step 5: Add the cross-view drift test**

In `core/tests/test_architecture_inventory.py`, load the architecture generator with its existing helper and assert exact equality:

```python
def test_architecture_and_lens_share_one_mcp_inventory() -> None:
    lens = discover_mcp_servers(REPO_ROOT)
    architecture = generate_architecture_inventory.discover_engines(REPO_ROOT)

    assert [
        (item.server_name, item.source_path, item.tools)
        for item in lens
    ] == [
        (item.server_name, item.source, item.tools)
        for item in architecture
    ]
```

- [ ] **Step 6: Regenerate the architecture inventory and run focused checks**

Run:

```bash
python3 scripts/generate-architecture-inventory.py
python3 -m pytest core/tests/test_lens_catalog_enriched_discovery.py core/tests/test_architecture_inventory.py -q
python3 -m ruff check core/lens_catalog_discovery.py scripts/generate-architecture-inventory.py core/tests/test_lens_catalog_enriched_discovery.py core/tests/test_architecture_inventory.py
```

Expected: all tests pass; generated inventory still reports 11 servers and 146 tools; no generated drift remains.

- [ ] **Step 7: Commit the canonical inventory**

```bash
git add core/lens_catalog_discovery.py scripts/generate-architecture-inventory.py core/tests/test_lens_catalog_enriched_discovery.py core/tests/test_architecture_inventory.py docs/architecture/INVENTORY.md
git commit -m "fix: share complete MCP catalogue discovery"
```

### Task 2: Reconcile the held connection doorway with release truth

**Repository:** Dex Core

**Files:**
- Delete: `.claude/skills/connect/SKILL.md`
- Modify: `core/lens-catalog/registry.json`
- Modify: `core/lens-catalog/enriched-registry.json`
- Modify: `core/lens_catalog_discovery.py`
- Create: `core/tests/test_lens_catalog_release_truth.py`
- Regenerate: `docs/architecture/INVENTORY.md`

- [ ] **Step 1: Write a release-truth test that fails on the current contradiction**

```python
from __future__ import annotations

import json
from pathlib import Path

from core.lens_catalog_discovery import discover_active_skills, discover_system_engines

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_held_connect_doorway_is_not_shipped_as_active() -> None:
    active_ids = {item.capability_id for item in discover_active_skills(REPO_ROOT)}
    registry = json.loads((REPO_ROOT / "core/lens-catalog/registry.json").read_text())
    registry_ids = {entry["id"] for entry in registry["entries"]}
    engines = {item.capability_id: item for item in discover_system_engines(REPO_ROOT)}

    assert not (REPO_ROOT / ".claude/skills/connect/SKILL.md").exists()
    assert "connect" not in active_ids
    assert "connect" not in registry_ids
    assert engines["connection-manager-engine"].availability == "parked"
```

- [ ] **Step 2: Run the truth test and prove the contradiction**

Run:

```bash
python3 -m pytest core/tests/test_lens_catalog_release_truth.py -q
```

Expected: FAIL because the active skill and active catalogue annotation exist while no parked engine record exists.

- [ ] **Step 3: Remove the unsafe person-facing doorway from the release tree**

Delete `.claude/skills/connect/SKILL.md` and remove only the registry object whose `id` is `connect`. Do not delete `core/integrations/connection-manager/`; the engine remains shipped groundwork.

- [ ] **Step 4: Represent the shipped-but-unavailable engine honestly**

Add this group to `discover_system_engines`:

```python
"connection-manager-engine": (
    "parked",
    [
        path
        for path in (root / "core/integrations/connection-manager").rglob("*")
        if path.is_file() and "tests" not in path.relative_to(root / "core/integrations/connection-manager").parts
    ],
),
```

Add this exact publisher annotation to `core/lens-catalog/enriched-registry.json`:

```json
{
  "id": "connection-manager-engine",
  "capability_class": "system-engine",
  "availability": "parked",
  "title": "Connection Manager Engine",
  "value": "Provides local connection custody and provider metadata, but its person-facing doorway remains unavailable.",
  "jobs_served": ["evolve-the-system-itself"],
  "foundation_capabilities": ["safe-change-recovery", "compounding-correctability"],
  "prerequisites": ["A reviewed person-facing doorway must be released before this engine can be used."],
  "trade_offs": ["The engine is shipped groundwork and must not be recommended as currently usable."]
}
```

- [ ] **Step 5: Regenerate and run all release-truth checks**

Run:

```bash
python3 scripts/generate-architecture-inventory.py
python3 -m pytest core/tests/test_lens_catalog_release_truth.py core/tests/test_lens_catalog_discovery.py core/tests/test_lens_catalog_enriched_discovery.py -q
python3 -m ruff check core/lens_catalog_discovery.py core/tests/test_lens_catalog_release_truth.py
```

Expected: PASS; no active `connect` doorway; a parked connection engine remains visible for honest coverage.

- [ ] **Step 6: Commit the release-truth correction**

```bash
git add .claude/skills/connect/SKILL.md core/lens-catalog/registry.json core/lens-catalog/enriched-registry.json core/lens_catalog_discovery.py core/tests/test_lens_catalog_release_truth.py docs/architecture/INVENTORY.md
git commit -m "fix: keep held connection doorway out of releases"
```

### Task 3: Gate and generate the corrected signed catalogue

**Repository:** Dex Core

**Files:**
- Modify: `core/lens-catalog/registry.json`
- Modify: `scripts/generate-dex-lens-catalog.py`
- Modify: `core/tests/test_dex_lens_catalog_generation.py`
- Modify: `docs/examples/dex-lens-catalog-enriched-preview.json`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add exact class, identity and activity assertions**

```python
def test_corrected_catalogue_has_complete_truthful_identity_sets(tmp_path: Path) -> None:
    envelope = _generate_enriched_release(tmp_path)
    entries = envelope["catalogue"]["capabilities"]
    by_id = {entry["capability_id"]: entry for entry in entries}

    assert "dex-pipedrive-mcp" in by_id
    assert len(by_id["dex-pipedrive-mcp"]["tools"]) == 15
    assert "connect" not in by_id
    assert by_id["connection-manager-engine"]["availability"] == "parked"
    assert len(entries) == len(by_id)
    assert sum(len(entry.get("tools", [])) for entry in entries) == 146
```

- [ ] **Step 2: Run the generator test and prove it fails before the correction is wired through**

```bash
python3 -m pytest core/tests/test_dex_lens_catalog_generation.py::test_corrected_catalogue_has_complete_truthful_identity_sets -q
```

Expected: FAIL on the missing Pipedrive entry, active Connect entry, or absent parked engine.

- [ ] **Step 3: Advance the catalogue identity and regenerate the example**

Set `catalog_version` in `core/lens-catalog/registry.json` to `5`; the enriched path adds one and therefore emits catalogue version `6`. Regenerate through the existing guarded command, never by editing the example:

```bash
python3 scripts/generate-dex-lens-catalog.py --enriched-preview --output-dir outputs/lens-catalogue
cp outputs/lens-catalogue/dex-lens-catalog-enriched-preview.json docs/examples/dex-lens-catalog-enriched-preview.json
```

The implementation must continue to refuse signing and release filenames on `--enriched-preview`; the real release path remains the only signing path.

- [ ] **Step 4: Add the release note without claiming publication**

Under `Unreleased`, record:

```markdown
- Dex Lens catalogue discovery now shares Core's complete MCP inventory, including integration-owned servers, and refuses to publish a held doorway as active.
```

- [ ] **Step 5: Run Core's complete catalogue gates**

```bash
python3 scripts/generate-dex-lens-catalog.py --output-dir outputs/lens-default
python3 scripts/generate-dex-lens-catalog.py --enriched-preview --output-dir outputs/lens-enriched
python3 -m pytest core/tests/test_lens_catalog_discovery.py core/tests/test_lens_catalog_enriched_discovery.py core/tests/test_lens_catalog_release_truth.py core/tests/test_dex_lens_catalog_generation.py core/tests/test_architecture_inventory.py -q
python3 -m ruff check core/lens_catalog_discovery.py scripts/generate-dex-lens-catalog.py core/tests/test_lens_catalog_discovery.py core/tests/test_lens_catalog_enriched_discovery.py core/tests/test_lens_catalog_release_truth.py core/tests/test_dex_lens_catalog_generation.py
git diff --exit-code -- docs/architecture/INVENTORY.md
```

Expected: both generators succeed; all focused tests and Ruff pass; the generated architecture inventory is clean.

- [ ] **Step 6: Commit the corrected unpublished catalogue source**

```bash
git add core/lens-catalog/registry.json scripts/generate-dex-lens-catalog.py core/tests/test_dex_lens_catalog_generation.py docs/examples/dex-lens-catalog-enriched-preview.json CHANGELOG.md
git commit -m "fix: gate truthful complete Lens catalogue"
```

## Workstream B — deterministic, privacy-safe Lens evidence

### Task 4: Add the operational-state observation contract

**Repository:** Dex Lens

**Files:**
- Create: `src/capability_exchange/diagnosis/observations.py`
- Create: `tests/diagnosis/test_observations.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`

- [ ] **Step 1: Write schema tests before the model exists**

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    SafeAttribute,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def test_configuration_is_distinct_from_a_verified_outcome() -> None:
    observation = Observation(
        kind=ObservationKind.MCP_SERVER,
        identity="career-data",
        label="Career data",
        operational_state=OperationalState.DECLARED,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference="path-token:abc123",
        ),
        attributes=(SafeAttribute(key="transport", value="local-command"),),
    )

    assert observation.operational_state is OperationalState.DECLARED
    assert observation.operational_state is not OperationalState.OUTCOME_VERIFIED


def test_unknown_attribute_keys_and_secret_values_are_refused() -> None:
    with pytest.raises(ValidationError):
        SafeAttribute(key="api_token", value="secret-value")


def test_fingerprint_rejects_duplicate_observation_identity() -> None:
    item = Observation(
        kind=ObservationKind.SKILL,
        identity="daily-plan",
        label="Daily plan",
        operational_state=OperationalState.IMPLEMENTED,
        evidence=EvidenceItem(state="observed", captured_at=NOW, reference="path-token:a"),
    )
    with pytest.raises(ValidationError, match="duplicate observation"):
        EvidenceFingerprint(adapter_id="claude-code-local", collected_at=NOW, observations=(item, item))
```

- [ ] **Step 2: Run the tests and prove the contract is absent**

```bash
python3 -m pytest tests/diagnosis/test_observations.py -q
```

Expected: collection error because `capability_exchange.diagnosis.observations` does not exist.

- [ ] **Step 3: Implement the closed observation model**

```python
from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence import EvidenceItem

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
_SAFE_ATTRIBUTE_KEYS = frozenset({
    "transport", "tool-count", "config-scope", "schedule", "run-at-load",
    "hook-event", "release-id", "source-kind", "provider-count", "receipt-age",
})


class OperationalState(StrEnum):
    DECLARED = "declared"
    IMPLEMENTED = "implemented"
    INSTALLED = "installed"
    ENABLED = "enabled"
    LOADED = "loaded"
    RECENTLY_RUN = "recently-run"
    OUTCOME_VERIFIED = "outcome-verified"
    DISABLED = "disabled"
    STALE = "stale"
    CONFLICTING = "conflicting"
    ABSENT = "absent"
    NOT_ASSESSED = "not-assessed"
    UNSUPPORTED = "unsupported"


class ObservationKind(StrEnum):
    RELEASE = "release"
    SKILL = "skill"
    MCP_SERVER = "mcp-server"
    MCP_TOOL = "mcp-tool"
    AUTOMATION = "automation"
    HOOK = "hook"
    INTEGRATION_REGISTRY = "integration-registry"
    HEALTH_CHECK = "health-check"
    RECOVERY_PROOF = "recovery-proof"


class SafeAttribute(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    value: str = Field(min_length=1, max_length=160)

    @field_validator("key")
    @classmethod
    def _allowlisted_key(cls, value: str) -> str:
        if value not in _SAFE_ATTRIBUTE_KEYS:
            raise ValueError(f"attribute key {value!r} is not allowlisted")
        return value

    @field_validator("value")
    @classmethod
    def _single_safe_line(cls, value: str) -> str:
        if any(marker in value.lower() for marker in ("token", "secret", "password", "credential")):
            raise ValueError("attribute values may not carry secret-shaped material")
        if "\n" in value or "\r" in value:
            raise ValueError("attribute values are one bounded line")
        return value


class Observation(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: ObservationKind
    identity: str
    label: str = Field(min_length=1, max_length=160)
    operational_state: OperationalState
    evidence: EvidenceItem
    attributes: tuple[SafeAttribute, ...] = ()

    @field_validator("identity")
    @classmethod
    def _identity_shape(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError("observation identity must be a bounded stable id")
        return value


class EvidenceFingerprint(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    adapter_id: str
    collected_at: datetime
    observations: tuple[Observation, ...]
    limits: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _unique_observations(self) -> Self:
        keys = [(item.kind, item.identity) for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("fingerprint contains a duplicate observation")
        return self
```

- [ ] **Step 4: Inventory every new field as ephemeral and never shared**

Add entries under the existing diagnosis boundary for `EvidenceFingerprint`, `Observation`, and `SafeAttribute`; every entry uses `storage: none`, `sharing: never`, and the deletion path `not persisted`.

- [ ] **Step 5: Run schema, inventory and lint checks**

```bash
python3 -m pytest tests/diagnosis/test_observations.py tests/boundary/test_inventory.py tests/boundary/test_check_inventory.py -q
python3 -m ruff check src/capability_exchange/diagnosis/observations.py tests/diagnosis/test_observations.py
```

Expected: PASS.

- [ ] **Step 6: Commit the observation contract**

```bash
git add src/capability_exchange/diagnosis/observations.py tests/diagnosis/test_observations.py src/capability_exchange/boundary/data_inventory.yaml
git commit -m "feat: model operational evidence separately"
```

### Task 5: Discover release identity, MCPs, hooks, integrations and scheduled work

**Repository:** Dex Lens

**Files:**
- Create: `src/capability_exchange/adapters/claude_code/discovery.py`
- Create: `tests/adapters/claude_code/test_discovery.py`
- Modify: `src/capability_exchange/adapters/claude_code/contract.py`
- Modify: `src/capability_exchange/adapters/claude_code/inventory_cli.py`
- Modify: `tests/adapters/claude_code/test_inventory_cli.py`
- Modify: `tests/adapters/claude_code/test_secrets.py`

- [ ] **Step 1: Write the legacy-vault discovery test with synthetic names**

```python
def test_discovers_whole_system_without_equating_presence_with_working(
    tmp_path: Path,
) -> None:
    system = synthetic_legacy_system(tmp_path)
    fingerprint = discover_fingerprint(system.snapshot, collected_at=NOW)
    by_key = {(item.kind, item.identity): item for item in fingerprint.observations}

    assert by_key[(ObservationKind.RELEASE, "dex-core")].attributes[0].value == "v0.8.3"
    assert by_key[(ObservationKind.MCP_SERVER, "career-data")].operational_state is OperationalState.DECLARED
    assert by_key[(ObservationKind.AUTOMATION, "nightly-check")].operational_state is OperationalState.IMPLEMENTED
    assert by_key[(ObservationKind.HEALTH_CHECK, "system-doctor")].operational_state is OperationalState.IMPLEMENTED
    assert by_key[(ObservationKind.INTEGRATION_REGISTRY, "local-integrations")].operational_state is OperationalState.IMPLEMENTED
    assert (ObservationKind.MCP_TOOL, "career-data:unknown") not in by_key
```

- [ ] **Step 2: Add canary tests that forbid secret retention**

```python
def test_mcp_and_hook_discovery_never_retains_secret_values(tmp_path: Path) -> None:
    canary = "DEX_LENS_CANARY_DO_NOT_RETAIN"
    snapshot = snapshot_with_configs(
        tmp_path,
        mcp_env={"API_TOKEN": canary},
        hook_command=f"runner --token {canary}",
    )

    rendered = discover_fingerprint(snapshot, collected_at=NOW).model_dump_json()

    assert canary not in rendered
    assert "API_TOKEN" not in rendered
    assert "--token" not in rendered
```

- [ ] **Step 3: Run the focused tests and prove discovery is too narrow**

```bash
python3 -m pytest tests/adapters/claude_code/test_discovery.py tests/adapters/claude_code/test_secrets.py -q
```

Expected: FAIL because the new discovery module and whole-system observations do not exist.

- [ ] **Step 4: Implement bounded parsers with one public entry point**

`discovery.py` exposes exactly this interface:

```python
from datetime import datetime

from capability_exchange.adapters.claude_code.snapshot import InspectionSnapshot
from capability_exchange.diagnosis.observations import EvidenceFingerprint


def discover_fingerprint(
    snapshot: InspectionSnapshot,
    *,
    collected_at: datetime,
    live_states: tuple[LiveState, ...] = (),
) -> EvidenceFingerprint:
    observations = (
        *_release_observations(snapshot, collected_at),
        *_skill_observations(snapshot, collected_at),
        *_mcp_observations(snapshot, collected_at),
        *_hook_observations(snapshot, collected_at),
        *_integration_observations(snapshot, collected_at),
        *_automation_observations(snapshot, collected_at, live_states),
        *_health_and_recovery_observations(snapshot, collected_at),
    )
    return EvidenceFingerprint(
        adapter_id="claude-code-local",
        collected_at=collected_at,
        observations=_fold_exact_duplicates(observations),
        limits=_render_limits(snapshot),
    )
```

Parser rules are fixed:

```python
MCP_CONFIG_BASENAMES = frozenset({
    ".mcp.json", "mcp.json", "settings.json", ".claude.json", "config.toml",
})
AUTOMATION_SUFFIXES = frozenset({".plist", ".cron", ".service", ".timer"})
INTEGRATION_BASENAMES = frozenset({"registry.json", "config.yaml", "config.yml"})
RELEASE_BASENAMES = frozenset({"CHANGELOG.md", "VERSION", ".dex-version"})
```

JSON/TOML traversal may retain only MCP server names, transport class, hook event name and action count. Plist/systemd/cron parsing may retain only label, cadence, fixed program basename and state evidence. Commands, arguments, environment blocks, URLs, note bodies and credential-shaped keys never enter an observation.

- [ ] **Step 5: Expand only the diagnostic-name priority set**

Add the parser basenames to `CLAUDE_CODE_DIAGNOSTIC_BASENAMES`. Do not broaden the approved roots or remove globally denied paths.

- [ ] **Step 6: Integrate the fingerprint into the existing inventory render**

Change `_render` to accept an `EvidenceFingerprint` and render separate sections for release identity, MCP servers, hooks, integrations, scheduled work, health/recovery and limits. The text for a declared MCP server must say “configured doorway; tools not enumerated” unless tool observations exist. The text for an implemented automation must say “written, not proved installed or running.”

- [ ] **Step 7: Run discovery, containment and secret tests**

```bash
python3 -m pytest tests/adapters/claude_code/test_discovery.py tests/adapters/claude_code/test_inventory_cli.py tests/adapters/claude_code/test_secrets.py tests/adapters/claude_code/test_containment.py tests/adapters/claude_code/test_surface_read_only.py -q
python3 -m ruff check src/capability_exchange/adapters/claude_code/discovery.py src/capability_exchange/adapters/claude_code/contract.py src/capability_exchange/adapters/claude_code/inventory_cli.py tests/adapters/claude_code/test_discovery.py
```

Expected: PASS; no canary appears in stdout, errors, fingerprint JSON or snapshots.

- [ ] **Step 8: Commit deterministic discovery**

```bash
git add src/capability_exchange/adapters/claude_code/discovery.py src/capability_exchange/adapters/claude_code/contract.py src/capability_exchange/adapters/claude_code/inventory_cli.py tests/adapters/claude_code/test_discovery.py tests/adapters/claude_code/test_inventory_cli.py tests/adapters/claude_code/test_secrets.py
git commit -m "feat: fingerprint whole personal AI systems"
```

### Task 6: Add explicit extra scopes and fixed live-state probes

**Repository:** Dex Lens

**Files:**
- Create: `src/capability_exchange/adapters/claude_code/live_state.py`
- Create: `tests/adapters/claude_code/test_live_state.py`
- Modify: `src/capability_exchange/adapters/claude_code/inventory_cli.py`
- Modify: `src/capability_exchange/adapters/claude_code/contract.py`
- Modify: `src/capability_exchange/skill/dex-lens/SKILL.md`

- [ ] **Step 1: Write consent and fixed-command tests**

```python
def test_extra_scope_is_read_only_only_when_named_explicitly(tmp_path: Path) -> None:
    vault = make_vault(tmp_path / "vault")
    global_config = make_config_root(tmp_path / "assistant-config")

    without = run_inventory(vault)
    with_scope = run_inventory(vault, "--also", str(global_config))

    assert "global-career-data" not in without.stdout
    assert "global-career-data" in with_scope.stdout


def test_live_probe_uses_fixed_argv_and_never_runs_vault_commands(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(live_state, "_run", lambda argv: calls.append(tuple(argv)) or "")

    live_state.collect_live_states(platform="darwin")

    assert calls == [("launchctl", "list")]
```

- [ ] **Step 2: Run and prove the CLI has no explicit multi-scope/live-state path**

```bash
python3 -m pytest tests/adapters/claude_code/test_live_state.py tests/adapters/claude_code/test_inventory_cli.py -q
```

Expected: FAIL on unknown `--also` and absent live-state module.

- [ ] **Step 3: Add the CLI flags with fail-closed validation**

```python
parser.add_argument(
    "--also",
    action="append",
    default=[],
    type=Path,
    metavar="FOLDER",
    help="An additional folder the person explicitly approved for this read-only inventory.",
)
parser.add_argument(
    "--include-live-state",
    action="store_true",
    help="Run fixed read-only operating-system status commands; never runs a command found in the inspected system.",
)
```

Resolve every `--also` path, reject `/`, the home directory, missing paths, overlaps with denied roots, and duplicates. Pass all approved roots to `claude_code_contract`; keep report/output storage outside every approved root.

- [ ] **Step 4: Implement fixed read-only probes**

```python
@dataclass(frozen=True)
class LiveState:
    kind: str
    identity: str
    operational_state: OperationalState
    captured_at: datetime


def collect_live_states(*, platform: str = sys.platform) -> tuple[LiveState, ...]:
    if platform == "darwin":
        return _parse_launchctl(_run(("launchctl", "list")))
    if platform.startswith("linux"):
        return _parse_systemd(_run(("systemctl", "--user", "list-units", "--no-legend", "--no-pager")))
    return ()
```

`_run` uses `subprocess.run` with a tuple from this module, `shell=False`, a 10-second timeout, a minimal environment, and no inspected-system values in argv or environment.

- [ ] **Step 5: Teach the skill to request scope before calling the flags**

The skill must name the additional folder and live-state question in plain language, wait for the person's answer, and call neither flag after a refusal. It must explain that live state means “whether the operating system says a scheduled job is loaded,” not “whether its outcome is correct.”

- [ ] **Step 6: Run security and read-only checks**

```bash
python3 -m pytest tests/adapters/claude_code/test_live_state.py tests/adapters/claude_code/test_inventory_cli.py tests/adapters/claude_code/test_containment.py tests/test_read_only_promise.py -q
python3 -m ruff check src/capability_exchange/adapters/claude_code/live_state.py src/capability_exchange/adapters/claude_code/inventory_cli.py tests/adapters/claude_code/test_live_state.py
```

Expected: PASS.

- [ ] **Step 7: Commit explicit scopes and probes**

```bash
git add src/capability_exchange/adapters/claude_code/live_state.py src/capability_exchange/adapters/claude_code/inventory_cli.py src/capability_exchange/adapters/claude_code/contract.py src/capability_exchange/skill/dex-lens/SKILL.md tests/adapters/claude_code/test_live_state.py tests/adapters/claude_code/test_inventory_cli.py
git commit -m "feat: inspect approved global and live state"
```

## Workstream C — complete two-way comparison and evaluation

### Task 7: Add the complete comparison ledger

**Repository:** Dex Lens

**Files:**
- Create: `src/capability_exchange/diagnosis/comparison.py`
- Create: `tests/diagnosis/test_comparison.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`

- [ ] **Step 1: Write completeness and recommendation-limit tests**

```python
def test_ledger_requires_one_disposition_per_catalogue_entry() -> None:
    catalogue = catalogue_with("system-doctor", "backup-proof", "career-data")
    with pytest.raises(ValidationError, match="catalogue identity set"):
        ComparisonLedger.for_catalogue(
            catalogue,
            capabilities=(capability_with_entries("system-health", "system-doctor"),),
        )


def test_ledger_refuses_more_than_three_recommendations() -> None:
    with pytest.raises(ValidationError, match="at most three"):
        ledger_with_dispositions(
            Disposition.WORTH_BORROWING,
            Disposition.WORTH_BORROWING,
            Disposition.WORTH_BORROWING,
            Disposition.WORTH_BORROWING,
        )


def test_same_name_without_method_evidence_cannot_be_shared() -> None:
    with pytest.raises(ValidationError, match="method evidence"):
        disposition("system-doctor", Disposition.SHARED, evidence=())
```

- [ ] **Step 2: Run the tests and prove the ledger does not exist**

```bash
python3 -m pytest tests/diagnosis/test_comparison.py -q
```

Expected: import/collection failure.

- [ ] **Step 3: Implement the ledger's closed vocabulary and invariants**

```python
class Disposition(StrEnum):
    STRONG_HERE = "strong-here"
    SHARED = "shared"
    WORTH_BORROWING = "worth-borrowing"
    DEX_SHOULD_LEARN = "dex-should-learn"
    FRAGILE_OR_CONTRADICTORY = "fragile-or-contradictory"
    NOT_RELEVANT = "not-relevant"
    NOT_ASSESSED = "not-assessed"


class CatalogueDisposition(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    catalogue_id: str
    disposition: Disposition
    capability_id: str
    evidence_references: tuple[str, ...] = ()
    method_compared: bool = False
    reason: str

    @model_validator(mode="after")
    def _claims_have_evidence(self) -> Self:
        grounded = {
            Disposition.STRONG_HERE,
            Disposition.SHARED,
            Disposition.WORTH_BORROWING,
            Disposition.DEX_SHOULD_LEARN,
            Disposition.FRAGILE_OR_CONTRADICTORY,
        }
        if self.disposition in grounded and not self.evidence_references:
            raise ValueError("a scored disposition requires evidence")
        if self.disposition is Disposition.SHARED and not self.method_compared:
            raise ValueError("shared requires method evidence, not name similarity")
        return self


class HumanCapability(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    capability_id: str
    title: str
    job_ids: tuple[str, ...]
    catalogue_ids: tuple[str, ...]
    person_observation_ids: tuple[str, ...]


class ComparisonLedger(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    catalogue_version: int
    catalogue_sha256: str
    capabilities: tuple[HumanCapability, ...]
    entries: tuple[CatalogueDisposition, ...]
    reciprocal_answer: str

    @model_validator(mode="after")
    def _bounded_recommendations(self) -> Self:
        count = sum(item.disposition is Disposition.WORTH_BORROWING for item in self.entries)
        if count > 3:
            raise ValueError("a report may recommend at most three Dex additions")
        return self
```

Add a `for_catalogue` constructor that takes the verified `CatalogueV2`, rejects missing/extra/duplicate catalogue IDs, requires every `HumanCapability.catalogue_ids` value to exist, and allows `reciprocal_answer` to be the exact honest empty result `No transferable method cleared the evidence bar.`

- [ ] **Step 4: Inventory the ledger fields and run checks**

```bash
python3 -m pytest tests/diagnosis/test_comparison.py tests/boundary/test_inventory.py tests/boundary/test_check_inventory.py -q
python3 -m ruff check src/capability_exchange/diagnosis/comparison.py tests/diagnosis/test_comparison.py
```

Expected: PASS.

- [ ] **Step 5: Commit the ledger contract**

```bash
git add src/capability_exchange/diagnosis/comparison.py tests/diagnosis/test_comparison.py src/capability_exchange/boundary/data_inventory.yaml
git commit -m "feat: account for every catalogue entry"
```

### Task 8: Generate and validate ledger templates from the verified catalogue

**Repository:** Dex Lens

**Files:**
- Modify: `src/capability_exchange/catalogue/agent.py`
- Modify: `src/capability_exchange/catalogue/cli.py`
- Modify: `tests/catalogue/test_agent_surface.py`
- Modify: `tests/catalogue/test_catalogue_cli.py`

- [ ] **Step 1: Write the verified template test**

```python
def test_ledger_template_contains_every_entry_and_release_identity(verified_catalogue) -> None:
    rendered = json.loads(render_catalogue_ledger_template(verified_catalogue.state))

    assert rendered["catalogue_version"] == 5
    assert rendered["catalogue_sha256"] == verified_catalogue.state.content_sha256
    assert {item["catalogue_id"] for item in rendered["entries"]} == {
        item.capability_id for item in verified_catalogue.state.catalogue.capabilities
    }
    assert all(item["disposition"] == "not-assessed" for item in rendered["entries"])
```

- [ ] **Step 2: Run and prove the template command is absent**

```bash
python3 -m pytest tests/catalogue/test_agent_surface.py tests/catalogue/test_catalogue_cli.py -q
```

Expected: FAIL on missing renderer/CLI option.

- [ ] **Step 3: Add the renderer and CLI flag**

```python
def render_catalogue_ledger_template(state: VerifiedCatalogueStateV2) -> str:
    payload = {
        "catalogue_version": state.metadata.catalog_version,
        "catalogue_sha256": state.content_sha256,
        "capabilities": [],
        "entries": [
            {
                "catalogue_id": entry.capability_id,
                "disposition": "not-assessed",
                "capability_id": "unassigned",
                "evidence_references": [],
                "method_compared": False,
                "reason": "Not assessed yet.",
            }
            for entry in sorted(state.catalogue.capabilities, key=lambda item: item.capability_id)
        ],
        "reciprocal_answer": "No transferable method cleared the evidence bar.",
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
```

Add `--ledger-template` to `dex-lens catalogue`; it remains downstream of signature verification and prints JSON only after verification succeeds.

- [ ] **Step 4: Run catalogue and signature-failure tests**

```bash
python3 -m pytest tests/catalogue/test_agent_surface.py tests/catalogue/test_catalogue_cli.py tests/catalogue/test_v2_verifier.py -q
python3 -m ruff check src/capability_exchange/catalogue/agent.py src/capability_exchange/catalogue/cli.py tests/catalogue/test_agent_surface.py tests/catalogue/test_catalogue_cli.py
```

Expected: PASS; tampered or unsigned catalogues never produce a ledger template.

- [ ] **Step 5: Commit the verified template**

```bash
git add src/capability_exchange/catalogue/agent.py src/capability_exchange/catalogue/cli.py tests/catalogue/test_agent_surface.py tests/catalogue/test_catalogue_cli.py
git commit -m "feat: scaffold complete catalogue comparisons"
```

### Task 9: Enforce the two-way report and store its ledger

**Repository:** Dex Lens

**Files:**
- Create: `src/capability_exchange/reports/ledger.py`
- Create: `tests/reports/test_ledger.py`
- Modify: `src/capability_exchange/reports/cli.py`
- Modify: `src/capability_exchange/reports/store.py`
- Modify: `tests/reports/test_evidence_gate.py`
- Modify: `tests/reports/test_reports_cli.py`
- Modify: `tests/test_skill_report_template.py`

- [ ] **Step 1: Add failing report-contract tests**

```python
@pytest.mark.parametrize(
    "missing",
    ("## What is working especially well", "## What Dex should learn from you"),
)
def test_two_way_sections_are_required(missing: str) -> None:
    problems = missing_report_requirements(COMPLETE_TWO_WAY.replace(missing, ""))
    assert any(missing.removeprefix("## ") in problem for problem in problems)


def test_more_than_three_recommendation_findings_are_refused() -> None:
    report = COMPLETE_TWO_WAY.replace(
        "## Worth borrowing from Dex\n",
        "## Worth borrowing from Dex\n" + "\n".join(
            f"### Suggestion {index}\n> evidence\n> - `system.md`"
            for index in range(4)
        ),
    )
    assert any("at most three" in problem for problem in missing_report_requirements(report))


def test_save_refuses_a_ledger_that_does_not_match_the_verified_catalogue() -> None:
    result = reports_main(["check", report_path, "--ledger", incomplete_ledger_path])
    assert result == 2
```

- [ ] **Step 2: Run and prove the current save gate accepts a one-way report**

```bash
python3 -m pytest tests/reports/test_evidence_gate.py tests/reports/test_ledger.py tests/reports/test_reports_cli.py tests/test_skill_report_template.py -q
```

Expected: FAIL because reciprocal/strength substance, recommendation count and ledger completeness are not enforced.

- [ ] **Step 3: Add structural report checks**

Require these level-two headings in this order:

```python
_REQUIRED_TWO_WAY_SECTIONS = (
    "what i read",
    "what is working especially well",
    "what dex should learn from you",
    "worth borrowing from dex",
    "fragility and contradictions",
    "coverage and limits",
    "what happens next",
)
```

The first two judgement sections require at least one quoted finding with a source, except the reciprocal section may contain exactly `No transferable method cleared the evidence bar.` The `Worth borrowing` section may contain zero to three `###` findings. `Fragility and contradictions` remains separate and cannot satisfy a strength or recommendation requirement.

- [ ] **Step 4: Load and verify a ledger for `check` and `save`**

Add `--ledger PATH` to both subcommands. `reports/ledger.py` parses `ComparisonLedger`, checks the catalogue SHA/version against the last verified local catalogue state, and returns all problems without writing. `save` writes the Markdown and a same-stem `.ledger.json` sidecar in Lens app storage only after both gates pass.

```python
def _gate(
    markdown: str,
    previous: SavedReport | None,
    ledger: ComparisonLedger | None,
    verified_catalogue: VerifiedCatalogueStateV2 | None,
) -> list[str]:
    problems = missing_report_requirements(markdown)
    if unaccounted := missing_comparison_with(previous, markdown):
        problems.append(unaccounted)
    problems.extend(ledger_problems(ledger, verified_catalogue))
    return problems
```

- [ ] **Step 5: Prove `check` remains write-free and `save` remains outside the inspected roots**

```bash
python3 -m pytest tests/reports/test_evidence_gate.py tests/reports/test_ledger.py tests/reports/test_reports_cli.py tests/reports/test_report_store.py tests/test_skill_report_template.py -q
python3 -m ruff check src/capability_exchange/reports/ledger.py src/capability_exchange/reports/cli.py src/capability_exchange/reports/store.py tests/reports/test_ledger.py
```

Expected: PASS; `check` creates nothing; `save` creates Markdown plus ledger sidecar only in Lens app storage.

- [ ] **Step 6: Commit the two-way report gate**

```bash
git add src/capability_exchange/reports/ledger.py src/capability_exchange/reports/cli.py src/capability_exchange/reports/store.py tests/reports/test_ledger.py tests/reports/test_evidence_gate.py tests/reports/test_reports_cli.py tests/test_skill_report_template.py
git commit -m "feat: require complete two-way Lens reports"
```

### Task 10: Rewrite the agent workflow around fingerprint, version distance and reciprocal value

**Repository:** Dex Lens

**Files:**
- Modify: `src/capability_exchange/skill/dex-lens/SKILL.md`
- Modify: `tests/test_skill_report_template.py`
- Create: `tests/test_skill_complete_diagnosis.py`
- Modify: `docs/skill-README.md`

- [ ] **Step 1: Pin the workflow requirements in tests**

```python
def test_skill_requires_version_and_method_before_same_capability() -> None:
    text = SKILL.read_text()
    assert "A matching name is a candidate, not proof" in text
    assert "version distance" in text.lower()
    assert "configured MCP server is not its tool list" in text
    assert "written is not running" in text


def test_skill_requires_praise_reciprocity_and_three_or_fewer() -> None:
    text = SKILL.read_text()
    assert "What is working especially well" in text
    assert "What Dex should learn from you" in text
    assert "at most three" in text.lower()
    assert "repeat the best strength" in text
```

- [ ] **Step 2: Run and prove the current skill permits the failed experience**

```bash
python3 -m pytest tests/test_skill_complete_diagnosis.py tests/test_skill_report_template.py -q
```

Expected: FAIL on the new pinned requirements.

- [ ] **Step 3: Replace the comparison phases with this exact sequence**

1. Read the previous report and decisions.
2. Ask permission for each additional global or live-state scope.
3. Generate the evidence fingerprint and establish release distance.
4. Fetch and verify the signed catalogue; generate its complete ledger template.
5. Build the person's human Capabilities first, using observations and methods rather than names.
6. Group relevant catalogue entries beneath those Capabilities.
7. Fetch a full brief for every potential recommendation and every same-name/shared verdict.
8. Fill every ledger disposition; unavailable entries cannot be recommended.
9. Choose two to five strengths, at least one reciprocal answer or the honest empty result, and at most three Dex recommendations.
10. Keep fragility and housekeeping separate.
11. Check and save report plus ledger.
12. In chat, repeat the best strength, reciprocal answer and most useful next move.

Include these non-negotiable lines verbatim:

```markdown
A matching name is a candidate, not proof. Compare the method, supporting machinery, version and usable state before calling a Capability shared.

A configured MCP server is not its tool list. Unless the tools were enumerated safely, say the doorway is configured and the tools are Unknown.

Written is not running. A script, installer or schedule template proves implementation only; installed, loaded, recently run and outcome-verified are separate claims.
```

- [ ] **Step 4: Replace the report template and final-chat contract**

Use the order enforced in Task 9. Under the template, state that the final chat answer is incomplete unless it repeats the best evidenced strength, the reciprocal answer, and the first recommended move.

- [ ] **Step 5: Run skill, package and copy-parity checks**

```bash
python3 -m pytest tests/test_skill_complete_diagnosis.py tests/test_skill_report_template.py tests/test_packaging.py -q
python3 -m ruff check tests/test_skill_complete_diagnosis.py tests/test_skill_report_template.py
```

Expected: PASS; the packaged wheel still contains the canonical skill and documentation agrees with the CLI.

- [ ] **Step 6: Commit the complete Diagnosis workflow**

```bash
git add src/capability_exchange/skill/dex-lens/SKILL.md tests/test_skill_complete_diagnosis.py tests/test_skill_report_template.py docs/skill-README.md
git commit -m "feat: make Lens diagnosis complete and reciprocal"
```

### Task 11: Build the anonymised legacy-system evaluation

**Repository:** Dex Lens

**Files:**
- Create: `tests/evals/__init__.py`
- Create: `tests/evals/legacy_system_fixture.py`
- Create: `tests/evals/test_legacy_system_diagnosis.py`
- Create: `tests/fixtures/evals/legacy-system-expected.json`
- Create: `src/capability_exchange/evaluation/__init__.py`
- Create: `src/capability_exchange/evaluation/diagnosis.py`

- [ ] **Step 1: Write the expected outcome contract with invented identities**

```json
{
  "release_id": "v0.8.3",
  "observations": {
    "mcp_servers_declared": 7,
    "mcp_tools_known": 0,
    "automation_implemented": 2,
    "automation_loaded": 0,
    "health_collectors": 1,
    "restore_proofs": 0
  },
  "required_capabilities": [
    "career-development-loop",
    "role-specific-planning-loop",
    "human-reviewed-suggestions",
    "follow-through-safety-net"
  ],
  "required_dispositions": {
    "current-system-health": "worth-borrowing",
    "verified-backup-restore": "worth-borrowing",
    "career-development": "shared"
  },
  "forbidden_claims": [
    "servers cover every tool",
    "hooks are stronger than proactive health",
    "same name means same capability",
    "written means running",
    "backup activity proves restore"
  ],
  "max_recommendations": 3,
  "requires_strength": true,
  "requires_reciprocal_answer": true
}
```

- [ ] **Step 2: Create the synthetic system entirely from invented content**

`legacy_system_fixture.py` writes a temporary tree containing:

```python
FILES = {
    "CHANGELOG.md": "# Changes\n\n## v0.8.3 — Local Services\n",
    ".mcp.json": json.dumps({"mcpServers": {
        "career-data": {"command": "python3", "args": ["role_data_server.py"]},
        "calendar-data": {"url": "https://example.invalid/mcp"},
    }}),
    ".claude/settings.json": json.dumps({"mcpServers": {
        "career-data": {"command": "python3", "env": {"API_TOKEN": CANARY}},
        "work-data": {"command": "node"},
    }, "hooks": {"SessionStart": [{"command": f"runner --token {CANARY}"}]}}),
    ".scripts/nightly-check.sh": "#!/bin/sh\nexit 0\n",
    ".scripts/install-nightly-check.sh": "#!/bin/sh\nexit 0\n",
    ".scripts/nightly-check.plist.template": PLIST_TEMPLATE,
    "core/utils/system_doctor.py": "def check():\n    return {'state': 'unknown'}\n",
    "core/mcp/role_data_server.py": CAREER_SERVER_SOURCE,
    "System/integrations/registry.json": json.dumps({"providers": ["calendar", "work"]}),
    "System/integrations/config.yaml": "calendar:\n  enabled: true\n",
    "skills/career-coach/SKILL.md": CAREER_SKILL,
    "skills/role-plan-custom/SKILL.md": ROLE_PLAN_SKILL,
    "skills/review-suggestions-custom/SKILL.md": REVIEW_SKILL,
    "skills/follow-through-custom/SKILL.md": FOLLOW_THROUGH_SKILL,
}
```

The constants use invented prose only. The fixture contains no real service names, personal names, paths, counts, excerpts, hashes or identifiers from the private source.

- [ ] **Step 3: Write the layered evaluator**

```python
@dataclass(frozen=True)
class EvaluationResult:
    observation_errors: tuple[str, ...]
    capability_errors: tuple[str, ...]
    comparison_errors: tuple[str, ...]
    report_errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not (
            self.observation_errors
            or self.capability_errors
            or self.comparison_errors
            or self.report_errors
        )


def evaluate_diagnosis(
    *,
    fingerprint: EvidenceFingerprint,
    ledger: ComparisonLedger,
    report_markdown: str,
    expected: Mapping[str, object],
) -> EvaluationResult:
    return EvaluationResult(
        observation_errors=_observation_errors(fingerprint, expected),
        capability_errors=_capability_errors(ledger, expected),
        comparison_errors=_comparison_errors(ledger, expected),
        report_errors=_report_errors(report_markdown, expected),
    )
```

- [ ] **Step 4: Pin every original failure as a regression test**

```python
def test_legacy_system_eval_rejects_the_original_bad_report(tmp_path: Path) -> None:
    fingerprint, ledger, expected = build_case(tmp_path)
    result = evaluate_diagnosis(
        fingerprint=fingerprint,
        ledger=ledger,
        report_markdown=ORIGINAL_FAILURE_SHAPE,
        expected=expected,
    )

    assert not result.passed
    assert any("tool inventory" in error for error in result.observation_errors)
    assert any("reciprocal" in error for error in result.report_errors)
    assert any("same-name" in error for error in result.comparison_errors)


def test_legacy_system_eval_accepts_a_grounded_two_way_report(tmp_path: Path) -> None:
    fingerprint, ledger, expected = build_complete_case(tmp_path)
    result = evaluate_diagnosis(
        fingerprint=fingerprint,
        ledger=ledger,
        report_markdown=COMPLETE_TWO_WAY_REPORT,
        expected=expected,
    )
    assert result.passed, result
```

- [ ] **Step 5: Run evaluation, privacy and hostile-input tests**

```bash
python3 -m pytest tests/evals/test_legacy_system_diagnosis.py tests/adapters/claude_code/test_secrets.py tests/fixtures/hostile -q
python3 -m ruff check src/capability_exchange/evaluation tests/evals
```

Expected: PASS; the evaluation's allowlist test confirms that every fixture identity and excerpt is invented.

- [ ] **Step 6: Commit the anonymised evaluation**

```bash
git add src/capability_exchange/evaluation tests/evals tests/fixtures/evals
git commit -m "test: gate complete encouraging Lens diagnosis"
```

### Task 12: Verify the whole result and prepare review PRs

**Repositories:** Dex Core, then Dex Lens

**Files:**
- Modify only if verification exposes a genuine defect
- Update: `docs/STATUS.md` and release handoff records only when their current claims are no longer true

- [ ] **Step 1: Run Core's focused and full Python gates on normal disk**

```bash
export TMPDIR=/srv/dex-dev/tmp/lens-complete-diagnosis
mkdir -p "$TMPDIR"
python3 -m pytest core/tests/test_lens_catalog_discovery.py core/tests/test_lens_catalog_enriched_discovery.py core/tests/test_lens_catalog_release_truth.py core/tests/test_dex_lens_catalog_generation.py core/tests/test_architecture_inventory.py -q
python3 -m pytest core/tests/ core/mcp/tests/ core/migrations/tests/ -m "not fuzz" -q
python3 -m ruff check core scripts
```

Expected: all checks pass.

- [ ] **Step 2: Run Lens's focused and full gates**

```bash
python3 -m pytest tests/diagnosis/test_observations.py tests/adapters/claude_code/test_discovery.py tests/adapters/claude_code/test_live_state.py tests/diagnosis/test_comparison.py tests/reports tests/catalogue tests/evals -q
python3 -m pytest tests -q
python3 -m ruff check src tests
python3 -m build
```

Expected: all tests, Ruff and package build pass.

- [ ] **Step 3: Run containment, egress and installer proofs**

```bash
python3 -m pytest tests/egress tests/adapters/claude_code/test_containment.py tests/adapters/claude_code/test_surface_read_only.py tests/test_read_only_promise.py -q
python3 scripts/section6_live_bridge_proof.py
```

Expected: no user-data egress; signed catalogue verification succeeds; read-only guarantees remain green.

- [ ] **Step 4: Dogfood the candidate against the private archive one final time**

Run the archive safety preflight again, generate a fresh private fingerprint, and compare only aggregate adjudicated outcomes. The pass conditions are:

- old release identity found;
- all configured MCP server identities retained, with no invented tool coverage;
- older Doctor, Career and connection methods distinguished from current Dex methods;
- source-only scheduled work never called active;
- at least two grounded strengths and one reciprocal idea;
- at most three Dex recommendations;
- no raw path, note prose, secret-shaped value or source identifier in output.

After the result is recorded privately, resolve the two exact paths from the private audit checkpoint, confirm that neither path is inside a repository, and remove only the temporary fingerprint workspace and the Devbox inbox copy. Verify both are absent. Leave the separately owned source archive untouched and recoverable.

- [ ] **Step 5: Perform GitHub preflight in each runner**

```bash
getent hosts github.com
gh auth status --hostname github.com
gh api user --hostname github.com --jq '"GITHUB_OK: @" + .login'
git ls-remote upstream HEAD
```

Expected: DNS, GitHub API identity and remote Git access all succeed in the same runner that will push.

- [ ] **Step 6: Push separate branches and open draft PRs**

Core PR first; Lens PR references the Core PR but remains independently testable against its synthetic catalogue fixture. Do not merge or release from this step.

- [ ] **Step 7: Reconcile Mission Control, Dispatch and release handoff**

Record the PRs and green evidence. Keep the work `in_review` until both PRs merge. After merges, use the Mission Control closeout workflow; describe publication as pending until separately approved Core and Lens releases are live and the website route is reverified.

## Final completion proof

The work is complete only when:

1. Core architecture inventory and signed-catalogue MCP identity/tool sets are exact and cannot drift.
2. Held `/connect` instructions are absent from active releases; the shipped engine is visibly unavailable.
3. Lens distinguishes declared, implemented, installed, loaded, recently run and outcome-verified evidence.
4. Same-name methods do not count as shared without version and method evidence.
5. A configured MCP server never implies unseen tools.
6. Every signed catalogue entry receives exactly one disposition in a validated ledger.
7. Reports require grounded strengths, a reciprocal answer, no more than three Dex suggestions, separated fragility and a repeated positive close in chat.
8. The anonymised evaluation rejects the original failure shape and accepts the complete two-way shape.
9. Full Core and Lens suites, Ruff, packaging, containment, egress and signed-catalogue proofs are green.
10. Private source material has been removed from the Dex Devbox audit inbox/work area, with no raw material ever committed or published.
