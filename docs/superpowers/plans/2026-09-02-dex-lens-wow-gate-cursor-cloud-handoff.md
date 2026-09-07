# Dex Lens Wow Gate — Cursor Cloud handover

## Start here

- Repository: `davekilleen/dex-lens`
- Continue branch: `codex/lens-significant-capability-coverage`
- Draft pull request: <https://github.com/davekilleen/dex-lens/pull/53>
- Code checkpoint before this handover: `8171907cb4a7ab3c8451f7bc97bee6b8034457c0`
- Approved design: `docs/superpowers/specs/2026-09-02-dex-lens-wow-gate-design.md`
- Exact implementation plan: `docs/superpowers/plans/2026-09-02-dex-lens-autonomous-wow-gate.md`
- Related Core contract PR: <https://github.com/davekilleen/Dex/pull/689>
- Mission Control card PR: <https://github.com/davekilleen/dex-cards/pull/101>

This is a continuation checkpoint, not a request to restart or redesign the work.
The branch has a large, reviewed foundation and must remain a draft. Do not merge,
release, publish, sign, deploy, alter the live installer, or expose private
evaluation material.

## Outcome Dave approved

Build the Dex Lens “Wow Gate”: replace manually seeded conclusions with an
autonomous, evidence-bound Engine + MCP workflow that inspects the whole work
system, reconstructs connected workflows, and produces **up to 10** specific,
ranked Dex recommendations. The same report must also include grounded praise and
ideas Dex should learn from the inspected system.

The final proof is a no-help, read-only evaluation against Dave's private
repository, repeated after improvements until Lens:

1. recognises every agreed significant capability family;
2. produces useful surprises without unsupported claims;
3. has no manually injected proposal or conclusion provenance;
4. passes the automated Wow Gate at 90 or better, including every hard gate;
5. passes fresh specification and code-quality reviews; and
6. leaves both draft PRs green.

## What is already complete

### Significant-capability foundation

The branch already contains the signed family-contract work, deterministic family
assessment, richer observations, MCP-manifest discovery, backup/restore and task
adapter evidence, family coverage grading, evidence-honest explanations, and the
public four-class catalogue explanation. Treat these as the starting substrate,
not work to recreate.

### Wow Gate Task 1 — rank up to 10 recommendations

Complete and independently reviewed. The Engine owns the maximum of 10 and the
exact ordering: risk, relevance, workflow leverage, evidence strength, adoption
effort, then stable identity. The stored ledger, canonical digest, appendix, and
reload path all preserve that order and its evidence bindings.

Tracking commit: `feb12cf`.

### Wow Gate Task 2 — durable specialist work queue

Complete and independently reviewed. Eight bounded normal specialist packets plus
one locked sceptical packet are deterministic, persisted, resumable, auditable, and
limited to two attempts. `PENDING` is not terminal; only an exhausted second attempt
may become `UNRESOLVED`.

Tracking commit: `580fde4`.

### Wow Gate Task 3 — bind conclusions to issued work

Complete and independently reviewed. Every guided proposal is bound to its exact
run, packet, packet digest, role, candidate identity, evidence identities, and
observation identities. The sceptical pass can preserve or downgrade an immutable
normal candidate but cannot substitute a claim or inflate its ranking factors.

Tracking commit: `7510d27`.

### Wow Gate Task 4 — Engine-owned guided state machine

Implementation and specification review are complete through `8171907`.

- `ANALYSIS_PLANNED` and `ANALYSIS_COMPLETED` sit between job confirmation and
  comparison.
- New Engine requests default to guided analysis; genuinely old stored inputs
  migrate conservatively to inventory-only.
- `work(run_id)` returns the same next packet after restart.
- `submit_work(...)` validates against the exact packet, persists immutable attempt
  history, allows one retry, and treats an explicit empty response as insufficient
  evidence rather than fabricated completion.
- Guided comparison is built only from stored, reconciled work.
- Inventory-only legacy runs retain their old path and expose no semantic work.
- Queue, response, audit, and input artifacts are content-bound and tamper failures
  do not consume retries.

The independent specification reviewer found three real issues, all fixed with
regressions:

- `5a0f4d5`: a guided run can no longer briefly accept an old unbound proposal at
  the catalogue-verified stage;
- `d067ce8`: disagreement about recommendation factors stays honestly
  `NOT_ASSESSED` without preventing the sceptical pass or completion; and
- `8171907`: an altered diagnosis-input artifact fails closed rather than falling
  back to the candidate-scope mode.

Specification review verdict: **PASS** at `8171907`, with no remaining concrete
Task 4 criterion violation. A fresh code-quality review of Task 4 is intentionally
still outstanding and is the first continuation action below.

## Verification at this checkpoint

On the integrated branch at `8171907`:

- Task 4 focused run/work/specialist/interruption tests: green.
- Focused post-fix rerun: 125 tests collected and passed.
- Inventory: 947 inventoried fields, 155 stored with deletion paths, one transmitted
  through a closed reviewed path.
- Ruff over every Task 4 changed file: green.
- Full repository suite: exit 0 at 100%; 2,364 tests collected, 15 documented
  environment/platform skips, no failures.
- The previously pushed PR checkpoint (`7510d27`) has nine green GitHub checks,
  including Linux/macOS Python 3.11/3.12, containment, egress, live bridge, and the
  pilot-build release gate. GitHub CI must be rerun after this handover checkpoint
  is pushed.

Use the repository's own environment in Cursor Cloud. If it is absent, install the
development extras from `pyproject.toml`; do not depend on another worktree's venv.

## Continue in this exact order

### 1. Finish Task 4's second review gate

Run a fresh, read-only code-quality review over `7510d27..8171907`. Do not repeat
the passed specification review. Look for correctness, accidental complexity,
security/privacy regressions, persistence bugs, and missing adversarial coverage.
Fix only concrete findings with failing-first tests, then have a fresh reviewer
recheck them.

### 2. Task 5 — expose the same work protocol through MCP and CLI

Add the sixth read-only diagnosis MCP tool, `get_diagnosis_work`, and change the
existing singular tool `submit_specialist_proposal` to accept `run_id`, `packet_id`,
and a tuple/list of proposals before calling the Engine once. Do not rename that
published tool.

CLI requirements:

- `diagnosis prepare --root <folder> --mode guided-analysis`
- `diagnosis work --run <id> --json`
- `diagnosis submit --run <id> --packet <id> --proposal <json-file>`
- permit repeatable `--proposal`, read all files first, and submit one tuple so the
  same packet is not accidentally treated as multiple conflicting responses.

Adapter invariants:

- Direct, CLI, and MCP work bytes must be identical canonical compact JSON.
- Work output is exactly `{"packet": null}` or the packet's
  `dump_for_storage()` representation.
- Reuse the existing canonical JSON, hostile-payload, unknown-field, and structured
  error helpers.
- Keep all six MCP tools locally read-only. Add no shell, network, filesystem
  traversal, model-provider, installation, sending, or inspected-system mutation
  authority.
- Reject unknown top-level and nested fields; never echo hostile values in errors;
  keep CLI stdout protocol-only and put human guidance/refusals on stderr.
- Preserve `approve` unchanged.
- `evaluation/replay.py` is a hidden compatibility seam. Existing inventory replays
  are explicitly inventory-only; guided replay paths must drive the same
  `work`/`submit_work` loop and must not regain a shortcut.

### 3. Tasks 6–10 — finish the product path

Follow the checked-in plan exactly, one test-driven slice at a time:

1. Task 6: reconstruct safe, evidence-bound connected workflows.
2. Task 7: version the 14 significant capability families and generate conservative
   automatic facts.
3. Task 8: bind workflow insights, strengths, lessons for Dex, and up to 10 ranked
   recommendations into one typed canonical report/result.
4. Task 9: make the installed skill complete the Engine work loop in Claude Code,
   Codex, and other supported hosts without relying on the model to remember the
   next step.
5. Task 10: add the automated Wow Gate scorer and hard gates.

Do not collapse these tasks into one large rewrite. For every task: red test,
smallest implementation, focused verification, fresh specification review, then
fresh code-quality review.

### 4. Task 11 — private no-help evaluation loop

Only after Tasks 5–10 are connected, run the clean, read-only evaluation against the
private repository Dave supplied. The agent gets the repository and the product,
but no manual hints, seeded proposals, expected answers, or coaching during the run.

Private-material rule: never place the repository name, raw files, paths, personal
content, observations, report text, proposal text, or identifying counts in source,
tests, commits, PRs, Mission Control, Dispatch, logs intended for sharing, or this
handover. Record only aggregate gate scores and pass/fail results that cannot reveal
the source.

Loop: fresh run → score → classify failures → add general product logic and public
sanitised tests → independent review → fresh run. Stop only at the approved bar; do
not weaken the scorer to make a run pass.

### 5. Task 12 — final proof and draft handoff

Run the full repository gates, privacy checks, exact generated-file checks, adapter
conformance, interruption/replay tests, and fresh final reviews. Update both draft
PRs and reconcile Mission Control/Dispatch accurately. Leave the work draft-only for
Dave's explicit release decision.

## Test commands

Use the exact commands in each task. The common gates are:

```bash
python3 scripts/check_inventory.py
python3 -m pytest -q
ruff check .
git diff --check
```

Task 4 focused regression group:

```bash
python3 -m pytest \
  tests/diagnosis/test_run.py \
  tests/diagnosis/test_run_store.py \
  tests/diagnosis/test_orchestrator.py \
  tests/diagnosis/test_work.py \
  tests/diagnosis/test_specialists.py \
  tests/evals/test_interrupted_run.py -q
```

Before any GitHub fetch, push, or remote inspection in the Cursor runner, run:

```bash
getent hosts github.com
gh auth status --hostname github.com
gh api user --hostname github.com --jq '"GITHUB_OK: @" + .login'
git ls-remote origin HEAD
```

Classify DNS, HTTPS credentials, and SSH-route failures separately. Do not copy or
request secrets in chat.

## Branch, review, and tracking discipline

- Work in Cursor Cloud's isolated checkout. Never edit a shared dirty checkout.
- Fetch the continuation branch and use it directly if Cursor owns that checkout;
  otherwise create a continuation branch from its exact head and update PR #53.
- Preserve unrelated changes and never rewrite shared history or force-push.
- Keep PR #53 draft. Core PR #689 is also draft and was green at handover.
- The Mission Control card remains `in_progress`; never call the Wow Gate shipped
  before the private evaluation and final gates pass.
- Log only meaningful milestones in Dispatch, not test or commit noise.
- Do not merge either repository, publish a release, sign/serve a catalogue, deploy
  the website, or alter production without Dave's later explicit approval.

## Copy-paste Cursor Cloud prompt

```text
Continue the Dex Lens autonomous Wow Gate from branch
codex/lens-significant-capability-coverage. Do not restart or redesign it.

First read, in order:
1. docs/superpowers/plans/2026-09-02-dex-lens-wow-gate-cursor-cloud-handoff.md
2. docs/superpowers/specs/2026-09-02-dex-lens-wow-gate-design.md
3. docs/superpowers/plans/2026-09-02-dex-lens-autonomous-wow-gate.md

Tasks 1–4 are implemented through code checkpoint 8171907. Task 4's specification
review is PASS; begin with its still-outstanding fresh code-quality review over
7510d27..8171907, fix only concrete findings with failing-first tests, and re-review.
Then continue Tasks 5–12 in the exact handover order.

Keep conclusions Engine-owned and evidence-bound. The final report may contain up
to 10 ranked Dex recommendations plus grounded praise and ideas Dex should learn.
Use fresh specification and quality reviewers for every slice. Run the final
no-help evaluation read-only against Dave's private repository, but never expose any
private repository identity, path, file, observation, report text, or proposal in
source, tests, commits, PRs, Mission Control, Dispatch, or shared logs.

Keep PR #53 and the related Core PR #689 draft. Do not merge, sign, publish, release,
serve, deploy, alter the live installer, or touch production.
```
