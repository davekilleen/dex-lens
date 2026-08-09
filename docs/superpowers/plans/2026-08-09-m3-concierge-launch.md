# Dex Lens M3 Concierge Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a truthful, installable Dex Lens alpha that completes the approved read-only M3 journey—doorway, permission, collection, Job Map confirmation, diagnosis, and Capability Map—with the R3 safety posture and launch evidence needed for a public announcement.

**Architecture:** Keep the stdlib-only loopback transport small. Move journey state and rendering into focused modules, reuse the existing `InspectionJobStore` and diagnosis engine, and isolate request-security/cancellation machinery from product flow. Three workers build non-overlapping slices in separate Treehouse worktrees; the coordinator integrates them in `server.py`, runs adversarial review, and owns the final release evidence.

**Tech Stack:** Python 3.11+, stdlib HTTP server and subprocess/threading helpers, Pydantic domain models, pytest + Hypothesis, Ruff, GitHub Actions on Ubuntu and macOS.

---

## File map and ownership

- `src/capability_exchange/concierge/security.py`: atomic token, host, cookie, Origin, CSRF, expiry, and hostile-request policy.
- `src/capability_exchange/concierge/collection.py`: cancellable collection controller, live-scope snapshots, partial disposal, and honest fallback result.
- `tests/concierge/test_r3_security.py`, `test_r3_collection.py`: security and cancellation acceptance evidence.
- `src/capability_exchange/concierge/journey.py`: explicit stages, `InspectionJobStore` orchestration, full Success Contract confirmation, diagnosis/map generation, cleanup.
- `src/capability_exchange/concierge/views.py`: local-only HTML for permission, Job Map editing, fallback, and map.
- `tests/concierge/test_journey.py`: stage and Job Map behavior.
- `src/capability_exchange/concierge/server.py`: coordinator-owned integration point; workers must not overlap it unless assigned the security transport slice.
- `src/capability_exchange/concierge/cli.py`, `tests/concierge/test_cli.py`, `tests/test_packaging.py`: install/run doorway proof.
- `README.md`, `docs/STATUS.md`, `.github/workflows/ci.yml`: alpha boundary, quickstart, and CI evidence.

### Task 1: R3 request security and cancellable collection

**Files:**
- Create: `src/capability_exchange/concierge/security.py`
- Create: `src/capability_exchange/concierge/collection.py`
- Create: `tests/concierge/test_r3_security.py`
- Create: `tests/concierge/test_r3_collection.py`
- Modify: `src/capability_exchange/concierge/server.py`
- Modify only if needed for process cancellation: `src/capability_exchange/adapters/claude_code/containment.py`
- Test any containment change in: `tests/adapters/claude_code/test_containment.py`

- [ ] **Step 1: Write failing hostile-request tests.**

```python
def test_concurrent_bootstrap_replay_has_exactly_one_success(): ...
def test_expired_request_terminates_and_discards_session(): ...
def test_invalid_host_origin_csrf_and_cookie_terminate_session(): ...
def test_deep_link_and_websocket_upgrade_are_rejected(): ...
def test_server_constructor_refuses_non_loopback_bind(): ...
```

- [ ] **Step 2: Run the focused tests and record the expected failures.**

Run: `.venv/bin/python -m pytest -q tests/concierge/test_r3_security.py`

Expected: failures proving replay is racy, security failures do not terminate, hostile upgrades are not explicitly denied, or non-loopback construction is accepted.

- [ ] **Step 3: Implement atomic, fail-closed request security.**

The public policy should expose focused operations, not mutable token fields:

```python
class SecurityFailure(Exception):
    pass

class SessionSecurity:
    def consume_bootstrap(self, token: str, now: datetime) -> str: ...
    def validate_get(self, host: str, cookie: str, now: datetime) -> None: ...
    def validate_post(
        self, host: str, cookie: str, origin: str, csrf: str, now: datetime
    ) -> None: ...
    def terminate(self) -> None: ...
```

Use a lock around all state transitions; rotate the bootstrap into an HttpOnly `SameSite=Strict` cookie; set `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and a CSP with no third-party resources; terminate on every validation failure.

- [ ] **Step 4: Write failing collection tests.**

```python
def test_scope_shrink_before_next_batch_terminates_collection(): ...
def test_cancel_stops_inflight_collection_within_bound(): ...
def test_cancel_discards_envelope_proposals_contracts_map_and_partials(): ...
def test_ambiguous_cancel_hard_stops_the_collection_process(): ...
def test_containment_unavailable_returns_guided_fallback_not_verified(): ...
```

- [ ] **Step 5: Run collection tests and record the expected failures.**

Run: `.venv/bin/python -m pytest -q tests/concierge/test_r3_collection.py`

Expected: failures because the current collector is synchronous, revalidates only once, cannot kill in-flight work, and propagates containment errors.

- [ ] **Step 6: Implement cancellation and live-scope validation.**

Use canonical path plus stable filesystem identity for the approved scope. Revalidate before each collector batch and before publishing any result. The control surface must be explicit:

```python
class CollectionController:
    def start(self) -> None: ...
    def cancel(self, timeout_seconds: float = 2.0) -> None: ...
    def result(self) -> CollectionOutcome: ...
```

If cooperative cancellation cannot prove the child stopped, terminate/kill the process, discard partials, and return a closed failure state. Never publish an envelope after cancellation or a scope change.

- [ ] **Step 7: Run focused and containment regression tests.**

Run: `.venv/bin/python -m pytest -q tests/concierge/test_r3_security.py tests/concierge/test_r3_collection.py tests/adapters/claude_code/test_containment.py`

Expected: all pass; platform-specific skips remain explicit.

- [ ] **Step 8: Lint, self-review, and commit the isolated slice.**

Run: `.venv/bin/ruff check src/capability_exchange/concierge src/capability_exchange/adapters/claude_code/containment.py tests/concierge tests/adapters/claude_code/test_containment.py`

Commit: `Build fail-closed M3 session security and cancellation`

### Task 2: Real six-stage journey and Job Map editing

**Files:**
- Create: `src/capability_exchange/concierge/journey.py`
- Create: `src/capability_exchange/concierge/views.py`
- Create: `tests/concierge/test_journey.py`
- Do not modify `server.py`; the coordinator owns transport integration.

- [ ] **Step 1: Write failing stage and permission-copy tests.**

```python
def test_permission_stage_names_adapter_roots_exclusions_and_next_action(): ...
def test_no_collection_before_explicit_permission(): ...
def test_decline_at_each_stage_discards_session_state(): ...
def test_no_diagnosis_before_success_contract_confirmation(): ...
```

- [ ] **Step 2: Define the explicit journey state machine.**

```python
class ConciergeStage(StrEnum):
    PERMISSION = "permission"
    COLLECTING = "collecting"
    JOB_MAP = "job-map"
    DIAGNOSIS = "diagnosis"
    CAPABILITY_MAP = "capability-map"
    FALLBACK = "fallback"
    CLOSED = "closed"

class ConciergeJourney:
    def approve(self) -> None: ...
    def add_job(self, fields: JobDraftFields) -> InspectionJob: ...
    def edit_job(self, job_id: str, fields: JobDraftFields) -> InspectionJob: ...
    def discard_job(self, job_id: str) -> None: ...
    def confirm_job(self, job_id: str, fields: ContractFields) -> SuccessContract: ...
    def diagnose(self) -> CapabilityMap: ...
    def close(self) -> None: ...
```

- [ ] **Step 3: Run focused tests and verify they fail for missing behavior.**

Run: `.venv/bin/python -m pytest -q tests/concierge/test_journey.py`

- [ ] **Step 4: Reuse `InspectionJobStore` for every proposed/manual job.**

On collection, convert each proposal with `to_inspection_job()` and save it. Add/edit/remove operate only through the store. Confirmation must call `InspectionJobStore.confirm()` with user-supplied success evidence, privacy/approval/autonomy boundaries, importance, cadence, and timestamp; direct synthesized `SuccessContract` construction is forbidden in the concierge.

- [ ] **Step 5: Write and pass full Job Map form tests.**

Cover inferred labelling, add/edit/remove, invalid confirmation leaving the draft intact, confirmed draft bytes removed, and empty Job Map refusal.

- [ ] **Step 6: Build local-only views.**

All forms contain the supplied CSRF token; all inspected/job text is escaped. Render no script, external URL, iframe, image, analytics, storage API, fetch, or WebSocket. The fallback page must call evidence Supported/Reported/Unknown and never Verified.

- [ ] **Step 7: Generate diagnosis and jobs-first map only from confirmed contracts.**

Run `assess()` then `render_capability_map()`; keep the three axes visible and ensure no aggregate score/pass/fail is introduced.

- [ ] **Step 8: Run focused tests, lint, self-review, and commit.**

Run: `.venv/bin/python -m pytest -q tests/concierge/test_journey.py tests/jobs tests/diagnosis tests/capmap`

Run: `.venv/bin/ruff check src/capability_exchange/concierge/journey.py src/capability_exchange/concierge/views.py tests/concierge/test_journey.py`

Commit: `Build the editable read-only M3 concierge journey`

### Task 3: Installable doorway, quickstart, and announcement boundary

**Files:**
- Modify: `src/capability_exchange/concierge/cli.py`
- Create: `tests/concierge/test_cli.py`
- Modify: `tests/test_packaging.py`
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Do not mark M3 complete in `docs/STATUS.md`; the coordinator does that only after integrated proof.

- [ ] **Step 1: Write failing CLI lifecycle tests.**

```python
def test_no_open_prints_only_loopback_bootstrap_url(): ...
def test_missing_or_non_directory_root_is_refused_before_server_start(): ...
def test_interrupt_terminates_session_and_closes_listener(): ...
def test_help_explains_read_only_local_alpha_boundary(): ...
```

- [ ] **Step 2: Implement the narrow doorway behavior and pass tests.**

Keep the command `dex-lens <approved-root> [<approved-root>...] [--no-open]`. Validate roots without reading them. Print the one-time local URL. Always terminate session and close the listener in `finally`, including Ctrl-C.

- [ ] **Step 3: Write a clean-wheel install/run test.**

Build a wheel without isolation, create a temporary venv, install the wheel, run `dex-lens --help`, and assert required YAML/JSON/sandbox profile package data exists at runtime.

- [ ] **Step 4: Add user quickstart and honest alpha copy.**

README must state: Diagnose/Decide stages 1–6 only; approved local Claude Code roots; no adaptation, contribution, account, analytics, or supported pilot claim; macOS socket and bind-mount proof limits remain named. Replace present-tense Adapt/Contribute claims with roadmap wording.

- [ ] **Step 5: Extend CI coverage without weakening existing gates.**

Keep Ubuntu + macOS 14 × Python 3.11/3.12 and the conformance/inventory steps. Ensure the clean-wheel test and all M3 tests run in the normal suite; add a named M3 evidence step only if it covers the changed files.

- [ ] **Step 6: Run focused tests, lint, self-review, and commit.**

Run: `.venv/bin/python -m pytest -q tests/concierge/test_cli.py tests/test_packaging.py`

Run: `.venv/bin/ruff check src/capability_exchange/concierge/cli.py tests/concierge/test_cli.py tests/test_packaging.py`

Commit: `Make the Dex Lens alpha installable and announcement-safe`

### Task 4: Integrate transport, journey, and launch evidence

**Files:**
- Modify: `src/capability_exchange/concierge/server.py`
- Modify: `tests/concierge/test_local_server.py`
- Create: `tests/concierge/test_m3_end_to_end.py`
- Create: `tests/egress/test_m3_concierge_egress.py`
- Create: `tests/concierge/test_offline.py`
- Modify: `docs/STATUS.md`
- Modify only to correct stale implementation facts: `docs/handoff/HANDOFF.md`

- [ ] **Step 1: Write failing integration tests for every M3 stage.**

Drive real HTTP requests through doorway → permission → collection → add/edit/remove → full confirmation → diagnosis → Capability Map → close. Assert no diagnosis pre-confirmation and exact stage transitions.

- [ ] **Step 2: Wire `SessionSecurity`, `CollectionController`, `ConciergeJourney`, and views into `server.py`.**

The handler validates transport before routing. The journey owns product state. `/approve`, `/cancel`, `/jobs/add`, `/jobs/edit`, `/jobs/discard`, `/jobs/confirm`, `/diagnose`, and `/close` each perform one explicit transition. Every security/scope failure closes and discards the session.

- [ ] **Step 3: Prove zero writes and byte-identical exits.**

Hash content, metadata, and extended attributes before/after decline, cancel, fallback, full diagnosis, and close. No inspected-system file may change.

- [ ] **Step 4: Prove zero unapproved egress and no third-party resources.**

Run the full synthetic journey under the existing egress harness with canaries. Assert no sockets outside the loopback listener, no DNS, no canary or derivation on the wire, and no HTML resource/storage/analytics surface.

- [ ] **Step 5: Prove offline completion and honest catalog absence.**

Disable external network access in the test harness, complete stages 1–6, and assert the UI says it used no catalog rather than silently degrading.

- [ ] **Step 6: Run the full local verification suite.**

Run:

```bash
.venv/bin/ruff check . --exclude .venv
.venv/bin/python -m pytest -rs
.venv/bin/python -m capability_exchange.conformance \
  --adapter claude-code-local --self-check --require-os-enforcement
.venv/bin/python scripts/check_inventory.py
```

Expected: all Linux-relevant checks pass; macOS-only checks remain explicit pending CI; the bind-mount skip remains named as unproven rather than counted as a pass.

- [ ] **Step 7: Update status using proof, not intent.**

Mark M3 complete only if all M3 criteria are implemented and the relevant CI matrix is green. Otherwise name the exact residual and constrain the announcement to a preview.

- [ ] **Step 8: Commit, push, and open a draft PR.**

Do not merge or publish a release without Dave's explicit approval. Wait for all CI legs, review the final diff, and prepare announcement-safe wording tied to the verified claim boundary.
