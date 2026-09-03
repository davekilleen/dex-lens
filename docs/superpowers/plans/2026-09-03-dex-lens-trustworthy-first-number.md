# Dex Lens: A Trustworthy First Number

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make one Wow Gate score mean something, so a single read-only run
against a real personal system on the owner's own machine can be trusted, and
only an aggregate grade travels back.

**Architecture:** No new subsystems. Four repairs to what Tasks 5–10 already
built: the scorer must measure whether claims are supported rather than whether
the ledger has the right shape; the grader's second input must have a real
producer and be bound to the ledger it grades; the canary technique must
actually cover the guided path; and the CLI must guard what it prints the way
the MCP adapter already does.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, Ruff, the existing
deterministic diagnosis engine, and the packaged Dex Lens skill.

---

## Why this plan is narrow

Seven independent reviews on 2026-09-03 found roughly forty defects across
Tasks 4–10. Fixing all of them is a programme. This plan deliberately fixes
four, chosen by a single test: *without this, a run's score is not evidence.*

The reasoning is that nobody yet knows whether the autonomous Wow Gate approach
works, because no honest measurement of it exists. One trustworthy number
against a real system is the cheapest thing that answers that, and it decides
whether the remaining thirty-odd findings are worth working at all. Everything
excluded is named in **Deferred** below rather than dropped.

## Delivery boundary

This plan updates Lens draft PR #53. It does not authorise merge, release,
signing, catalogue publication, installer promotion, website deployment, or any
production change. Core PR #689 is unaffected: no schema, catalogue or contract
bytes change here.

The evaluation runs on the owner's own machine against their live system. The
inspected system's name, paths, filenames, observations, report text, proposal
text and identifying counts must never enter a commit, CI log, PR, or any
shared artifact. **Only the aggregate grade JSON returns.** That artifact was
confirmed on 2026-09-03 to contain scores and a hard-failure count and no
proposal text; Task 1 must not add content to it.

## Evidence this plan is built on

All findings below were reproduced against `45ceca5`.

- A ledger with all fourteen expectations `UNKNOWN` and evidence-free, zero
  observations, and every insight citing a fabricated evidence id scored
  **95/100, passed, zero hard failures** through the shipped
  `scripts/run_wow_gate.py`. An honest run with three real recommendations and
  genuinely assessed families scored **84 and failed**.
- `wow_gate.py:58-76` — `_significant_coverage` scores `UNKNOWN` identically to
  the five determinate states, so `scored` is always `len(WOW_EXPECTATIONS)`
  and the dimension is a constant 25. The `elif ... UNKNOWN` branch and the
  `scored < len(...)` penalty are both dead.
- `wow_gate.py:49-55` — `_workflow_quality` tests
  `len(edge.evidence_ids) >= 2`, which `WorkflowEdge.evidence_ids =
  Field(min_length=2)` (`workflows.py:69`) already guarantees. It counts edges.
- `wow_gate.py:101-114` — `_evidence_integrity` starts at 15 and has no
  reduction for absent or unresolvable evidence.
- `wow_gate.py:79-89` — `_recommendation_quality` awards 8 points for producing
  no recommendations at all.
- `wow_gate.py:131` — the `manual-proposal` hard failure gates on
  `audit.manual_submission_count > 0`, but `WorkReceipt.submission_route` is
  `Literal["engine-work-packet"]` (`work.py:318`) and `WorkAudit`'s validator
  derives the expected count from that same single-valued field
  (`work.py:596-607`). No valid `WorkAudit` can carry a non-zero count.
  `tests/evals/test_wow_gate.py:198` reaches the branch only with a
  `SimpleNamespace`.
- Three of the plan's nine named hard-failure classes have no implementation:
  dishonest operational state, digest drift (`queue_digest` is never compared
  against `queue_digest_for(...)`), and private canaries.
- `report.py:770-776` — `_validate_ledger_insights` raises only when
  `evidence_ids` is empty, which `Field(min_length=1)` (`comparison.py:107`)
  already prevents. It is a tautology and cannot fire. Nothing checks that an
  insight's evidence ids exist in the ledger.
- `scripts/run_wow_gate.py` requires `--audit`, but **no CLI or MCP surface
  emits a `WorkAudit`**, so the evaluation loop cannot be run as written.
  `grade_wow_run(ledger, audit=None)` never consults `ledger.work_audit`, and
  `orchestrator.py:815-821` closes a guided run with `work_audit = None` when
  the artifact is simply absent. `grep -rn "run_wow_gate" tests` returns
  nothing: the script has no test.
- `tests/evals/real_session_fixture.py:62` — `CANARY` is assigned to
  `SyntheticSessionInput.secret` and **never placed into the fingerprint, the
  ledger, or any proposal**; its own assignment is the only reference in the
  repository. `tests/evals/test_real_session_replay.py:307` then asserts the
  input contains no canary. The six test files added by Tasks 5–10 contain zero
  canary assertions.
- `cli.py:238-246` (`_write_canonical_json`) and the markdown path have no
  equivalent of `mcp_server.py`'s outbound screen. A canary, an absolute path
  and a note body were demonstrated reaching CLI stdout on a real run.
- `boundary/crashlog.py` redacts correctly and has **zero callers in `src/`**.

## File structure

Changed:

- `src/capability_exchange/diagnosis/wow_gate.py` — honest scoring, reachable
  hard failures.
- `src/capability_exchange/diagnosis/expectations.py` — evidence-bearing
  expectations.
- `src/capability_exchange/diagnosis/report.py` — an insight guard that can fire.
- `src/capability_exchange/diagnosis/work.py` — a submission route vocabulary
  that can express a manual submission.
- `src/capability_exchange/diagnosis/orchestrator.py` — fail closed on a missing
  work audit.
- `src/capability_exchange/diagnosis/cli.py` — outbound guard, crash boundary.
- `scripts/run_wow_gate.py` — grade from the bound audit, crash boundary.
- `tests/evals/real_session_fixture.py`, `tests/evals/test_real_session_replay.py`
  — a canary that is actually planted.

New:

- `tests/evals/test_run_wow_gate.py` — the grader script has no test today.

---

## Task 1: Make the scorer measure honesty, not shape

**Acceptance:** the fabricated ledger described in Evidence scores below 90 and
fails; an honest ledger still passes; every hard failure the plan names either
exists or is explicitly withdrawn in writing.

- [x] Red test: a ledger whose fourteen expectations are all `UNKNOWN` with
      empty `evidence_ids` scores 0 on `significant_coverage`, not 25.
- [x] Red test: an insight citing an evidence id held by nothing in the ledger,
      fingerprint or local entries is an `unsupported-claim` hard failure.
- [x] Red test: a ledger with zero ranked recommendations scores 0 on
      `recommendation_quality`, not 8.
- [x] Score `significant_coverage` from determinate states only. `UNKNOWN`
      scores nothing. An expectation with empty `evidence_ids` scores nothing
      even when its state is determinate.
- [x] Give `SignificantExpectation.evidence_ids` a `min_length`, or score it as
      unevidenced. **Scored, not typed.** The plan preferred the type, but
      `min_length` would make an evidence-free expectation unrepresentable, and
      `UNKNOWN` legitimately has no evidence — "we could not tell" is the one
      honest verdict that cannot cite anything. The constraint belongs on
      determinate states only, which the type cannot express without splitting
      the model. Scoring enforces it instead: a determinate state earns nothing
      unless its evidence resolves.
- [x] Replace `_workflow_quality`'s tautology. Score edges whose evidence ids
      are **distinct across the graph** and resolve to real evidence. An edge
      set that reuses one evidence pair everywhere scores as one corroboration,
      not as many.
- [x] Make `_evidence_integrity` derive from the proportion of claims whose
      evidence resolves, so absent evidence reduces it. Remove the `break` that
      caps the existing deduction at a single `-3`.
- [x] Replace `_validate_ledger_insights` in `report.py` with a check that every
      insight's evidence ids resolve within the ledger. Delete the tautology.
- [x] Implement `private-canary`: the grader refuses a ledger carrying a session
      canary, using `payload_guard.refuse_hostile_payload`.
- [x] Regression: the Evidence fabricated ledger fails; the honest ledger passes.
      Reproduced before the fix at **91/100, passed, zero hard failures**; after
      the fix **24, failed**, while a genuinely evidenced ledger scores **92 and
      passes**. Both are pinned in `tests/evals/test_wow_gate.py`.

### Decisions recorded while implementing (2026-09-03)

**`manual-proposal` and `digest-drift` are withdrawn as grader checks.** Both
are unreachable at the grader by construction, and for the same reason: the
model already enforces them. `WorkAudit`'s validator derives the expected
manual count from `WorkReceipt.submission_route`, which is
`Literal["engine-work-packet"]` (`work.py:596-607`), and it refuses any audit
whose `queue_digest` does not bind its own `packet_ids`
(`work.py:568-569`). A grader row for either would restate a model invariant
and could never fire — which is how the original `manual-proposal` gate came to
look like protection while providing none.

The check that *is* meaningful is cross-binding: whether the audit being graded
is the one this ledger was closed with. That moves to **Task 2**, where it
becomes "refuse when the supplied audit disagrees with `ledger.work_audit`".
Widening `submission_route` is not required and is not done.

**`dishonest-operational-state` is withdrawn** pending a definition that
distinguishes it from success. The `-3` deduction fired on
`IMPLEMENTED and (OUTCOME_VERIFIED or HEALTHY)`, which is the same condition
`report.py:864-872` uses to mean a capability is genuinely working well, so it
was either dead or backwards. It is replaced by proportional evidence scoring,
which is strictly stronger: `_evidence_integrity` now scores the fraction of
all claims whose evidence the ledger holds, rather than starting at full marks
and deducting three once.

**The grader proves internal consistency, never authenticity.** A ledger
declares its own evidence and the grader never sees the fingerprint the tokens
were minted from, so a wholly fabricated but internally consistent ledger still
grades well. This is stated in the module docstring so a passing score is not
mistaken for proof that conclusions came from the inspected system. The defence
against that case is upstream and remains open as
RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT.

**Two test fixtures were themselves unsupported** and had to be repaired before
they could show the grader accepting an honest ledger: both
`tests/evals/test_wow_gate.py` and `tests/diagnosis/test_report_model.py` built
ledgers whose insights cited two evidence identities while their dispositions
recorded only one.

```bash
python3 -m pytest -q tests/evals/test_wow_gate.py tests/diagnosis/test_expectations.py \
  tests/diagnosis/test_report_model.py
```

## Task 2: Give the grader a real, bound audit input

**Acceptance:** the evaluation loop can be run end to end from shipped commands,
and a ledger cannot be graded against an audit that is not its own.

- [x] Red test: `grade_wow_run` refuses when the supplied audit disagrees with
      `ledger.work_audit`.
- [x] Red test: a guided run whose `work-audit` artifact is missing fails closed
      instead of closing with `work_audit = None`.
- [x] Grade from `ledger.work_audit`, which is already bound into the canonical
      payload and the digest. Make `--audit` optional; when supplied, cross-check
      it and refuse on disagreement.
- [x] Remove the `audit=None` default path that skips both provenance gates
      while still returning a score.
- [x] `orchestrator.py:815-821` must refuse to complete a guided comparison when
      the work-audit artifact is absent.
- [ ] Emit the audit from a shipped surface so the loop needs no hand-extraction:
      include it in `dex-lens diagnosis result --format json`, and add
      `get_diagnosis_result`'s equivalent on the MCP side. Keep both read-only.
- [x] Create `tests/evals/test_run_wow_gate.py`: the script runs, discriminates,
      refuses a mismatched audit, and its output JSON carries only aggregates.

```bash
python3 -m pytest -q tests/evals/test_run_wow_gate.py tests/diagnosis/test_orchestrator.py \
  tests/diagnosis/test_cli.py tests/diagnosis/test_mcp_server.py
```

## Task 3: Plant the canary for real

**Acceptance:** a deliberately planted secret is proven absent from every
surface a person or a shared artifact can see, on the guided path.

- [x] Delete `test_real_session_replay.py:307`. It asserts the replay input
      contains no canary, which is the statement that the canary suite is empty.
- [x] Plant three shapes into `real_session_fingerprint()` labels, references and
      provenance: the session canary, a relative vault-shaped path, and a
      person-shaped name. All invented; nothing real. **Planted through a
      variant, not the default.** `planted_session_fingerprint()` extends the
      clean fixture with the three shapes; the default stays clean because
      every honest-path test (the orchestrator harness, adapter conformance,
      interrupted-run) collects through it, and a permanently hostile default
      would make the engine's new capture refusal the only reachable path.
- [x] Plant a canary into a `SpecialistProposal.reason` on a guided replay whose
      `proposals` are non-empty. `ReplayHarness` gained a `work_responder` so
      the guided corpus carries real specialist content, and
      `planted_session_ledger()` plants a reason for the comparison surface.
- [x] Red first: prove the planted canary reaches the rendered report **before**
      any guard lands. Observed at `5f05ee2`: the ledger plant reached the
      rendered markdown, the result JSON and the saved report; the fingerprint
      plant was retained verbatim in the fingerprint artifact; the proposal
      plant was recorded verbatim into the `work-responses` artifact. All
      three guard tests were run against the unguarded tree and failed with
      `DID NOT RAISE` before any guard was written.
- [x] Assert absence in all eight: work bytes, submit responses, the ledger
      artifact, the fingerprint artifact, the result JSON, the rendered markdown,
      CLI stdout, and CLI/MCP stderr. The guards landed in the engine, which is
      the retention authority the adapters share: `_capture` and
      `_compare_ledger` refuse with a typed `DiagnosisStateError` before
      writing the artifact, and `submit_work`/`submit` treat hostile content
      as a malformed specialist response that burns the bounded attempt and is
      recorded as an empty rejection. Refusals never echo the offending value.
      Each absence test carries a positive control proving the plant and the
      scan both work before absence is claimed.
- [x] Extend the assertions to the guided-only artifacts written at
      `orchestrator.py:1136-1142` (`work-queue`, `work-responses`, `work-audit`),
      which no canary scan reached before, plus `reconciled-proposals`.
      A structural test also proves the two shapes no pattern can detect —
      the person-shaped name and the vault-shaped relative path — never leave
      the fingerprint artifact for any of those surfaces.

```bash
python3 -m pytest -q tests/evals/ tests/diagnosis/test_report_model.py
python3 scripts/check_inventory.py
```

## Task 4: Guard what the CLI prints

**Acceptance:** the CLI cannot print inspected-system content that the MCP
adapter would refuse, and an unexpected crash cannot print vault text.

- [x] Red test: a canary or absolute path in a ledger reason does not reach
      `dex-lens diagnosis result --format json` stdout.
- [x] Apply `payload_guard.refuse_hostile_payload` to the diagnosis payload
      outputs: `work`, `submit`, and `result --format json`.
- [x] **Founder decision required — do not choose unilaterally.** The rendered
      report footer (`report.py:531-541`) prints the report location, which
      contains the owner's username, inside the most shareable artifact Lens
      produces. A blanket guard on markdown would refuse Lens's own output. The
      options are to drop the footer line, to render it relative, or to exempt it
      explicitly and guard everything else. This is tester-visible copy and
      belongs to the founder under WO-022. **Decided by the founder,
      2026-09-03: render it relative.** `_render_close` renders a home-rooted
      location as `~/…`; a location outside home renders as written. With no
      account name left in the render, the markdown output is guarded like
      every other outbound surface.
- [x] Wire `boundary/crashlog.py` into `diagnosis_main` and
      `scripts/run_wow_gate.py`: catch `Exception`, write the redacted log, print
      a fixed sentence. This is the module's first caller in `src/`.
- [x] Leave the consent surface alone. `cli.py:196-201, 255-260` prints approved
      root paths and the local token by design; that is the person's own screen
      before any reading happens.

```bash
python3 -m pytest -q tests/diagnosis/test_cli.py tests/evals/
python3 -m ruff check .
```

**Decisions recorded (2026-09-03):**

1. The report-footer question was put to the founder under WO-022 and
   **resolved the same day: render it relative.** `report.py` now renders a
   home-rooted location as `~/…` (`_home_relative_location`), and
   `result --format markdown` passes through `refuse_hostile_payload` like
   every other outbound surface. Both were demonstrated red-first: the
   /Users/-shaped footer reached the rendered markdown, and a canary-bearing
   markdown reached CLI stdout at exit 0, before the change.
2. Consequence of parity guarding to surface before the first real run:
   the guard vocabulary treats any `/Users/` string as hostile, so a stored
   result that carried `report.report_location` would be refused by
   `result --format json` on the CLI exactly as by `get_diagnosis_result` on
   MCP already today. Verified while recording this note: the bound location
   is a `PrivateAttr`, excluded from `model_dump`, so on the current tree it
   reaches **only the rendered markdown footer** — precisely the surface left
   unguarded pending this decision — and never the JSON dump. The location
   decision must still land before the first real evaluation run: until it
   does, the footer prints the owner's username inside the most shareable
   artifact Lens produces, and any resolution that moves or guards the
   location (a blanket markdown guard, or surfacing the location in the
   dump) makes Lens refuse a real macOS run's own output.

---

## Deferred

Named here so they do not disappear. Each is real, reproduced, and out of scope
for a first trustworthy number. The three marked **critical** must be resolved
before any release, whatever the evaluation says.

| Item | Evidence | Why deferred |
| --- | --- | --- |
| **critical** — guided compare trusts the stored `reconciled-proposals` artifact instead of re-deriving it; 20 forged recommendations citing an unminted evidence token were accepted against a cap of 10 | `orchestrator.py:797-805` | Does not affect an honest run's score; blocks release |
| **critical** — aggregate limits enforced only after every receipt is final, so eight specialists each citing two tokens wedges the run with no exit | `orchestrator.py:1218, 1238` | Will be hit by a real run; if the evaluation wedges, fix this first |
| **critical** — `for_catalogue` omits the six new fields, so a tampered saved ledger passes `report check` | `comparison.py:780-795`, `reports/ledger.py:66-84` | Affects reload, not the first grade |
| Task 6 is not finished: discovery never emits `trigger-kind`/`action-kind`/`target-kind`, so the workflow graph is empty on any real vault | `3eca587` did not touch `adapters/claude_code/discovery.py` | This is build work, not a repair. The first number will show a thin graph — that is an honest result, and informative. **Founder decision, 2026-09-03: dropped for now** — revisit only if the first real number shows the workflow dimension is where the value lives |
| The person-entity node copies runtime and health from the *skill* observation | `workflows.py:179-184` | Fabrication, but Task 1's evidence scoring reduces its reward |
| Appendix never extended for the new sections, so "exact references are in the appendix" is not kept | `report.py:1097-1167` | Task 1 checks evidence resolves; the appendix rendering is separate |
| Recommendations and fragility warnings render under "Connections Lens noticed" | `comparison.py:1121-1132` | Report copy; founder call |
| Storage inventory disagrees with reality: fields declared `storage: none` are written to disk via `model_dump` | `orchestrator.py:649, 830, 1290-1299` | Local artifacts only, never transmitted; needs its own decision about which side is wrong |
| `automatic.py` invents all five ranking factors as constants and deletes its `workflows` argument | `automatic.py:25, 55-61` | One rule, small blast radius |
| ~600–1000 artifact re-reads per run; 2× input is 2.9× time | `orchestrator.py:1102` | A real vault run may be slow. Revisit if the evaluation is impractically slow |
| `SKILL.md` reference table omits `--packet` and has no `work` row, contradicting the new loop | `SKILL.md:1003` | Would stall a host mid-run; fix before anyone but the founder runs it |
| Plan text errors: `docs/capability-reference.md` does not exist; the bare generator invocation is an error path | Task 12 gate dry-run | Documentation |

## Completion proof

- [ ] The fabricated ledger from Evidence scores below 90 and fails.
- [ ] An honest ledger still passes.
- [ ] Every hard failure the plan names either fires in a test or is withdrawn
      in writing.
- [ ] A planted canary is proven absent from all eight surfaces.
- [ ] `scripts/run_wow_gate.py` has tests and runs from shipped commands with no
      hand-extracted input.
- [ ] Full suite green, and every changed test file green when run alone —
      `45ceca5` fixed a defect where 26 tests failed in isolation, and the suite
      cannot re-acquire that blindness.
- [ ] `ruff check .`, `scripts/check_inventory.py`, `git diff --check` clean.
- [ ] PR #53 remains draft.
