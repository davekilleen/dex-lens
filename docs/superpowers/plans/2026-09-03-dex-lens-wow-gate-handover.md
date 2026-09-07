# Dex Lens Wow Gate — handover, 2026-09-03

## Start here

- Repository: `davekilleen/dex-lens`
- Branch: `codex/lens-significant-capability-coverage` (PR #53, **draft**)
- Head at handover: `db81f71`. All nine CI checks green.
- Governing standard: `docs/superpowers/plans/2026-09-03-dex-lens-wow-gate-completion-goal.md`
- Current plan: `docs/superpowers/plans/2026-09-03-dex-lens-trustworthy-first-number.md`
- Open risks: `docs/RISK-REGISTER.md` (three rows added today, all `Open`)
- Core counterpart: `davekilleen/Dex` PR #689, draft, unaffected by today's work

This is a continuation. Do not restart or redesign.

## The one thing to understand first

On the morning of 2026-09-03 this programme was fully implemented with a green
suite, and neither fact meant what it looked like. Seven independent reviews
found that a diagnosis which determined **nothing** — all fourteen significant
families `UNKNOWN`, no observations, every claim citing a fabricated evidence
identity — scored **91/100 and passed** through the shipped grader. An honestly
evidenced run scored 92.

The cause was not a shortage of tests. It was tests asserting things that were
true by construction: restating a `Field(min_length=…)` back to itself, reaching
a branch only through a `SimpleNamespace` the engine cannot produce, asserting
that an input contained no canary. They ran green forever while proving nothing.

Hence the goal now governing this work: **a task is finished only when its
behaviour is demonstrated** — each criterion proved by a test observed to fail
without the code it guards, and by a run of the real shipped command. Read the
goal document before writing anything.

## What has been done (this session)

Seven commits on top of the recovered continuation work. Each has a
failing-first test and was pushed only after a full green suite.

| Commit | What |
| --- | --- |
| `e827e18` | Replay comparer left on an old signature by `2d09851`; 26 guard tests were red. Adds a signature-conformance guard. |
| `5b2adb2` | CLI and MCP refused different specialist payloads: a bad file burned a packet attempt on one adapter and none on the other, and pydantic errors echoed vault text to stderr. Detection moved into `diagnosis/payload_guard.py` ahead of both. |
| `45ceca5` | `ComparisonLedger` only resolved if `work` was imported first; 26 tests failed when their files ran alone. Suite hid it through import order. |
| `0425d33` | The narrow plan. |
| `ba1a7cc` | **Task 1.** Scorer now measures supported claims, not ledger shape. Fabricated ledger went 91→24 and fails; honest stays 92 and passes. |
| `580de77` | Installer tests depended on an unpinned Homebrew Python; nine failed on one macOS runner and passed on another. Sealed PATH now carries the running interpreter. |
| `7d8e929` | **Task 2.** Grades the audit bound into the ledger; refuses another run's audit; `--audit` now optional so the loop runs from shipped commands; guided runs fail closed without their audit; `run_wow_gate.py` has its first tests. |
| `db81f71` | The completion goal. |

## What is next, in order

### Task 3 — plant the canary for real (started, nothing written)

The privacy no-go on running against a real system rests on this. `CANARY` is
defined at `tests/evals/real_session_fixture.py:23`, assigned to
`SyntheticSessionInput.secret` at line 62, and **placed nowhere else in the
repository**. `tests/evals/test_real_session_replay.py:307` then asserts the
replay input contains no canary — the assertion that the suite is empty.

Steps, in the plan:

1. Delete that line 307 assertion.
2. Plant three shapes into `real_session_fingerprint()` labels, `evidence.reference`
   and `provenance.relative_reference`: the canary, a relative vault-shaped path,
   and a person-shaped name. All invented.
3. Plant a canary into a `SpecialistProposal.reason` on a guided replay whose
   proposals are non-empty. `evaluation/replay.py:255-263` currently submits `()`
   for every packet, so the guided corpus carries no content at all.
4. **Red first**: prove the planted canary reaches the rendered report before any
   guard lands. A canary test that has never failed proves nothing.
5. Assert absence in all eight: work bytes, submit responses, the ledger artifact,
   the fingerprint artifact, the result JSON, the rendered markdown, CLI stdout,
   CLI/MCP stderr.
6. Extend to the guided-only artifacts at `orchestrator.py:~1136-1142`
   (`work-queue`, `work-responses`, `work-audit`), which no canary scan reaches.

### Task 4 — guard what the CLI prints

`mcp_server.py` screens outbound payloads; `cli.py:_write_canonical_json` and the
markdown path do not, and a reviewer demonstrated a canary, an absolute path and
a note body reaching CLI stdout on a real run. Apply
`payload_guard.refuse_hostile_payload` to `work`, `submit` and
`result --format json`. Wire `boundary/crashlog.py` into `diagnosis_main` and
`scripts/run_wow_gate.py` — it redacts correctly and has zero callers in `src/`.

Leave the consent surface alone: `cli.py:196-201, 255-260` prints approved roots
and the local token by design.

**Founder decision, do not choose alone:** the rendered report footer
(`report.py:531-541`) prints the report location, which contains the owner's
username, inside the most shareable artifact Lens produces. A blanket guard on
markdown would refuse Lens's own output. Options: drop the line, render it
relative, or exempt it explicitly and guard everything else.

### Then: pull the wedge forward before any real run

`RISK-GUIDED-RUN-WEDGE`. Aggregate limits (`MAX_EVIDENCE_IDS = 8`,
`MAX_RECOMMENDATIONS = 10`) are enforced only when the whole normal set is
reconciled, which first happens at the sceptical packet — after all eight normal
receipts are final. Eight specialists each citing two distinct engine-minted
tokens is enough. `submit_work` then raises *before* the retry is recorded,
`advance` refuses as incomplete, and `work` returns the same packet forever.

This is normal specialist behaviour, not an attack. It is the defect most likely
to be met by the first real run, and it presents as a hang. Fix it before
spending a run, not after.

## Traps found the hard way

- **Fixtures that cite evidence they do not record.** Two "honest" fixtures built
  ledgers whose insights cited two evidence identities while their dispositions
  recorded one. Both had to be repaired before they could demonstrate the grader
  accepting an honest ledger. Assume more exist.
- **`ComparisonLedger` has strict cross-validators.** Ranked recommendations must
  match ledger entries, which must match human capabilities, and a recommendation's
  `evidence_ids` must equal its entry's `evidence_references`. Building a valid
  fixture is fiddly; build it by adjusting the candidate, not the entry.
- **Do not add `min_length` to `SignificantExpectation.evidence_ids`.** `UNKNOWN`
  legitimately has no evidence — it is the one honest verdict that cannot cite
  anything. The constraint belongs on determinate states, and is enforced by
  scoring instead.
- **The grader proves internal consistency, never authenticity.** A ledger
  declares its own evidence and the grader never sees the fingerprint the tokens
  were minted from, so a wholly fabricated but self-consistent ledger still grades
  well. Said in the `wow_gate` module docstring. The defence is upstream and open
  as `RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT`.
- **Two hard failures were withdrawn, deliberately.** `manual-proposal` and
  `digest-drift` each restated an invariant `WorkAudit` enforces on itself, so
  neither could fire. Do not reinstate them without making them reachable. An
  unreachable guard is worse than none: it reads as protection.
- **Run every changed test file alone**, not just the suite. `45ceca5` fixed a
  defect where 26 tests passed only because collection order imported `work`
  first, and CI cannot catch that class because CI runs the whole suite.
- **macOS CI legs differ.** Runner images vary in whether Homebrew Python exists.
  `580de77` removed that dependency; if a macOS leg goes red on installer tests
  again, check the interpreter before assuming the change caused it.

## Verification, every time

```bash
python3 -m pytest -q                       # full suite
python3 -m pytest -q <each changed file>   # and alone
python3 -m ruff check .
python3 scripts/check_inventory.py
git diff --check
```

Baseline at `db81f71`: full suite exit 0, zero failures, 17 environment skips on
Linux; ruff clean; inventory OK at 985 fields.

## Rules that do not bend

- **Draft only.** No merge, release, signing, catalogue publication, installer
  promotion, website deployment, or production change. Both PRs stay draft.
- **Private material.** The inspected system's name, paths, filenames,
  observations, report text, proposal text and identifying counts never enter a
  commit, CI log, PR or shared artifact. Only aggregate scores travel. The
  evaluation runs on the owner's own machine; only the grade JSON returns.
- **Never skip, disable or quarantine a test to get green.** Never rewrite shared
  history. Fixes carry failing-first tests.
- The founder's copy of the vault (`dex-dave`) was cloned into a cloud container
  earlier today for evaluation purposes and **deleted**; nothing from it reached
  any commit. Do not re-clone it: the agreed model is that the run happens on the
  owner's machine and only the grade returns.

## Open questions for Dave

1. The report-footer decision in Task 4 above.
2. Whether to run the evaluation as soon as Tasks 3–4 land, or after the wedge
   fix. Recommendation: after the wedge fix.
3. Task 6 is not implemented for real systems — the discovery adapter never emits
   the `trigger-kind`/`action-kind`/`target-kind` attributes `build_workflow_graph`
   keys off, so the graph is empty outside its own fixtures. The first real number
   will show a thin workflow picture. That is an honest result, not a bug, but it
   should be expected rather than discovered.
