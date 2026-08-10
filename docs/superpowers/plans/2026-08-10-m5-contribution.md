# M5 Capability Contribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local Capability Card, consent, withdrawal, moderation, signed-catalog, and exact-disclosure contribution flow without requiring production hosting.

**Architecture:** Cards are inert, closed, versioned data with no raw attachment field. Local lifecycle ports use synthetic stores in tests; production identity/storage remains an external adapter. Trust derives only from moderation/catalog signatures, and transmitted bytes must equal the approved disclosure manifest.

**Tech Stack:** Python, Pydantic, Ed25519-compatible signature interface, pytest state machines, existing G2 boundary.

---

### Task 1: Closed Card schema and validation

**Files:**
- Create: `src/capability_exchange/cards/__init__.py`
- Create: `src/capability_exchange/cards/model.py`
- Create: `src/capability_exchange/cards/validation.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`
- Test: `tests/cards/test_model.py`
- Test: `tests/cards/test_validation.py`

- [ ] Write failing tests for missing declarations, raw examples, attachments, secrets, unique paths, third-party confidential text, PII, prompt injection, and unsafe instructions.
- [ ] Implement a closed immutable Card version with permissions, dependencies, provenance, rights, test status, and limitations; no trust or attachment field is representable.
- [ ] Implement structural and scanner validation with specific reason codes; scanner failure quarantines.
- [ ] Run focused tests and inventory checks green.

### Task 2: Disclosure and version consent

**Files:**
- Create: `src/capability_exchange/cards/disclosure.py`
- Create: `src/capability_exchange/contribution/consent.py`
- Test: `tests/cards/test_disclosure.py`
- Test: `tests/contribution/test_consent.py`

- [ ] Write failing tests proving exact outbound field/byte display, immutable version hashes, separate six permissions, and edit-forces-fresh-consent.
- [ ] Implement canonical serialization, byte-exact disclosure manifests, and per-version consent records.
- [ ] Re-run focused tests green.

### Task 3: Draft, submit, withdraw, and propagation

**Files:**
- Create: `src/capability_exchange/contribution/lifecycle.py`
- Create: `src/capability_exchange/contribution/provenance.py`
- Test: `tests/contribution/test_lifecycle.py`
- Test: `tests/contribution/test_withdrawal.py`

- [ ] Write model-based failing tests for draft→submitted→quarantined/reviewed/rejected/withdrawn, illegal transitions, unresolvable permission state, and propagation across every controlled store.
- [ ] Implement stable pseudonymous version-bound contributor references and synthetic store ports.
- [ ] Implement immediate withdrawal, minimal audit retention, quarantine on unconfirmed propagation, and the immutable shipped-release disclosure.
- [ ] Re-run state-machine tests green.

### Task 4: Moderation and catalog trust

**Files:**
- Create: `src/capability_exchange/contribution/moderation.py`
- Create: `src/capability_exchange/catalog/verify.py`
- Test: `tests/contribution/test_moderation.py`
- Test: `tests/catalog/test_verify.py`

- [ ] Write failing tests for inert reviewer rendering, rights attestation, conflict/self-approval refusal, scanner-down quarantine, timeout rejection, false self-trust, and tampered/unsigned catalog rejection.
- [ ] Implement AI-led scanner decisions plus a separate Dave-final approval port, with reviewer identity and conflict assertions.
- [ ] Implement signed catalog verification and last-verified-or-none fallback with explicit status.
- [ ] Run focused tests green.

### Task 5: Stage 9 and exact egress

**Files:**
- Modify: `src/capability_exchange/concierge/journey.py`
- Modify: `src/capability_exchange/concierge/server.py`
- Modify: `src/capability_exchange/concierge/views.py`
- Test: `tests/concierge/test_contribution_journey.py`
- Test: `tests/egress/test_m5_contribution_egress.py`

- [ ] Write failing tests proving diagnosis/adaptation need no account and identity is requested only after explicit contribution choice.
- [ ] Add local build/review/disclose/approve/submit/withdraw stage 9 transitions behind an intake port.
- [ ] Capture outbound contribution bytes and require byte equality with the approved manifest; reject any header/body field outside inventory.
- [ ] Run the M5 suites, full suite, lint, inventory, and wheel tests.

