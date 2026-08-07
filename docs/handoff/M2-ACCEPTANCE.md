# M2 Acceptance Verification (adversarial)

**Date:** 2026-08-07
**Scope:** HANDOFF.md Section 4, milestone **M2** — Job Map + diagnosis engine + Capability Map rendering: propose–confirm Job Map with Success Contract schema; `Inspection` state machinery; the eight-Foundation-Capability diagnosis engine with three-axis findings; jobs-first Capability Map rendering; G6 taxonomy classifier.
**Criteria source of truth:** `docs/handoff/sources/gates.md` (R1, G6, R2) plus HANDOFF Section 4's M2 #351/#352 conformance clause and the HANDOFF 1.5 vocabulary.
**Method:** run every instrument, then attempt to break each criterion with probes written for this review — 15 novel G6 evasion phrasings (including three languages the corpus lacked entirely), aggregate-score smuggling via runtime subclassing and `model_construct`, serialization of an `InspectionJob` through every serializer route (pydantic dump/json/dict, `TypeAdapter`, pickle), unconfirmed-job injections into the diagnosis engine (draft, lookalike dict, exact-type-evading subclass, forged lifecycle), and Evidence-Level-upgrade attempts through the correction path. Findings were fixed test-first (failing test first, then the fix), and the whole suite re-run.

**Standing rule applied throughout: no criterion is marked MET without a passing test to cite, and — since HANDOFF Section 4 defines done as passing *in CI* — without that test passing in CI.**

---

## 1. Instrument results (recorded, not claimed)

| Instrument | Command | Result (after this review) | Result (before this review) |
| --- | --- | --- | --- |
| Test suite | `python -m pytest` | **865 passed / 4 skipped** locally (3.13); **green on all 4 CI legs** — see the run below | 836 passed / 4 skipped (the 840 collected at last push) |
| Lint | `ruff check .` | **All checks passed** | passed |
| G2 inventory check | `python scripts/check_inventory.py` | **OK — 67 inventoried fields, 11 stored (all with registered deletion paths), 0 transmitted** | same |
| Adapter conformance | `python -m capability_exchange.conformance --adapter claude-code-local --self-check` | **CONFORMANT: every check passed** (5/5) | same |
| Adversarial probe battery (this review) | 36 probes across 5 families | **0 escapes / 36** | **13 escapes / 36** (Findings H and I below) |

**CI run [31192436387](https://github.com/davekilleen/dex-capability-exchange/actions/runs/31192436387) (commit `7856cd3`) — `success` on all four legs** (`ubuntu-latest` × py3.11/3.12, `macos-14` × py3.11/3.12), with `pytest`, `adapter-conformance-claude-code`, and `g2-inventory-check` all passing. The 4 local skips are the darwin-only M1 containment tests, green on the macOS legs.

---

## 2. Per-criterion verdict table

### R1 — Provisional `Inspection` state, in full

| Criterion | Verdict | Proving tests |
| --- | --- | --- |
| Only explicit user confirmation exits `Inspection` | **MET** | `tests/jobs/test_inspection.py::TestConfirmationIsTheOnlyExit` (6 tests: confirm produces the contract and removes the record; editing never exits; `edited` has no lifecycle parameter; save/reload never exits; failed confirmation leaves the job in `Inspection`); `tests/capmap/test_correct.py::TestJobEditsReenterInspection::test_full_r1_round_trip_confirmation_is_the_only_exit`; `tests/jobs/test_propose.py::test_nothing_in_the_module_returns_a_success_contract` (detection proposes, never enrolls) |
| `Inspection`-state objects type-level unrepresentable in Card/export/contribution payloads (not runtime-filtered) | **MET** | `tests/jobs/test_inspection.py::TestTypeLevelShareExclusion` (5 tests: `ConfirmedJobExport` refuses an `InspectionJob`, a mixed tuple, and emptiness; the field annotation names only `SuccessContract`; `dump_for_transmission` refuses structurally) plus **new** `::TestShareExclusionBypassRoutes` (4) closing the `model_construct`/`model_copy` routes (Finding I) |
| Discard removes the data from disk | **MET** | `tests/jobs/test_inspection.py::TestDiscardRemovesDataFromDisk` (4 tests: bytes verifiably gone; discarding nothing refused; the registered `delete-inspection-jobs` deletion path removes all jobs and covers the inventory) |
| Crafted export referencing an `Inspection` job ID is rejected | **MET** | `tests/jobs/test_inspection.py::test_crafted_export_referencing_an_inspection_job_id_is_rejected`; `::test_unknown_and_empty_requests_are_rejected_alike` (uniform refusal — never discloses whether the id exists); hypothesis property test `::test_no_unconfirmed_id_ever_resolves` |
| Corrupt/missing state metadata → treated as `Inspection` | **MET** | `tests/jobs/test_inspection.py::TestCorruptStateCoercion` (5 tests: missing lifecycle loads as `Inspection`; a crafted on-disk `"diagnosis"` claim loads as `Inspection`; hypothesis test over arbitrary corrupt lifecycle values; an unreadable record is corrupt-but-never-shareable; the corrupt-record error never echoes record contents) |

### #351/#352 conformance

| Criterion | Verdict | Proving tests |
| --- | --- | --- |
| Every finding carries exactly the three independent axes | **MET** | `tests/diagnosis/test_conformance_351_352.py::TestExactlyThreeIndependentAxes` (4 tests: the schema has exactly the three axis fields; the vocabularies are the #351 amendment verbatim; every produced finding carries all three; Working+Verified can still be Overbroad — independence); `tests/diagnosis/test_finding.py::TestThreeAxes` |
| No aggregate score, maturity rank, or resemblance percentage representable in any schema or report template — **schema test, not code review** | **MET** | `tests/diagnosis/test_no_aggregate_representable.py::TestAggregateIsUnrepresentable` — walks **every field of every model in the diagnosis/capmap tree including nested models** (and asserts the walk covers all models in both packages), rejects score/rank/percent-shaped field names, asserts **no field anywhere has a numeric type**, asserts every model forbids extras, and asserts no aggregate-named symbol is exported; `tests/jobs/test_success_contract.py::test_score_shaped_fields_are_unrepresentable`; renderer: `tests/capmap/test_render.py::TestVocabularyCompliance` (no "Avoid" term — scorecard, maturity score, etc. — in any rendered output or evidence wording) |
| Diagnosis consumes only confirmed Success Contracts + approved scope | **MET** | `tests/diagnosis/test_conformance_351_352.py::TestOnlyConfirmedContractsAndApprovedScope` (3 tests: `assess` takes exactly two data inputs; an `Inspection`-state job is rejected; nothing but a `SuccessContract` enters — dict lookalikes refused). Probes D1–D5 (§3.4) confirmed the exact-type check also defeats a `SuccessContract` **subclass** and a `model_construct`-forged lifecycle |
| Presence-of-configuration alone never yields Working or Verified (fixture test) | **MET** | `tests/diagnosis/test_conformance_351_352.py::TestPresenceAloneNeverWorkingOrVerified` (2 tests, incl. one over any configuration-only envelope); `tests/diagnosis/test_negative_rules.py` (the #351 negative rules as fixtures: file presence ≠ portability proof, chat history alone ≠ memory proof, read access never implies write permission, more configuration never upgrades the assessment, file presence never means healthy, diagnosis never mutates and offers no adaptation entry point) |

### G6 — High-impact job taxonomy that fails closed

| Criterion | Verdict | Proving tests |
| --- | --- | --- |
| Labeled corpus across all nine categories with **zero false negatives** (false positives recorded, never gated) | **MET** | `tests/taxonomy/test_g6_corpus.py::TestG6ZeroFalseNegatives::test_zero_false_negatives_across_the_labeled_corpus` over the **187-entry** corpus (was 171; this review added its 12 escapes plus 4 more — §3.1); `::TestCorpusShape` (≥15 examples per category, ≥30 benign, all three phrasing kinds per category, ≥2 non-English languages); false-positive rate recorded at **4/36 = 11.1%** (all four predate this review — send/legal/health stems on benign drafting/explaining jobs; acceptable by the gate's own design bias) |
| Euphemistic/multilingual evasion routes to high-impact | **MET — after Finding H was fixed** | `tests/taxonomy/test_g6_evasion.py::TestCanonicalEvasions` (the three gates.md evasions verbatim), `::TestEuphemisticEvasions` (20 phrasings), `::TestMultilingualEvasions` (es/fr/de), `::TestObfuscationAttempts` (case, accent-smuggling, letter-spacing, whitespace), and **new** `::TestNovelEvasionsM2Review` (13 phrasings written for this review, incl. Dutch/Italian/Portuguese — languages the corpus previously lacked — and Japanese exercising the unreadable-script fail-closed path) |
| Unclassifiable → high-impact | **MET** | `tests/taxonomy/test_classifier.py::test_unclassifiable_input_is_high_impact` (non-string, empty, no-words inputs), `::test_ambiguous_catch_all_scope_is_high_impact`, `::test_single_word_job_is_too_ambiguous_to_bound`, `::test_non_string_field_value_fails_closed`; structural invariant `::test_only_no_match_may_be_non_high_impact` and `::test_categories_without_high_impact_is_unrepresentable`; hypothesis tests `::test_total_over_arbitrary_text_and_deterministic`, `::test_never_raises_on_arbitrary_input` |
| Classifier unavailable → all jobs high-impact for the session | **MET** | `tests/taxonomy/test_g6_fail_closed_session.py` (6 tests: an error yields high-impact, not an exception; after one error **all** later jobs in the session are high-impact; a wrong-typed result is a classifier defect and fails closed; base exceptions are not swallowed; recovery requires a new session) |
| High-impact jobs never trigger automated adaptation (the M2 half) | **MET (taxonomy layer)** | `automated_adaptation_allowed` is the single predicate, false for every high-impact classification: `tests/taxonomy/test_classifier.py` invariant tests plus `tests/taxonomy/test_g6_evasion.py::TestBenignJobHighImpactAdaptationCrossover` (the taxonomy half of the G6+G3 layered test; the G3 allowlist layer lands at M4 per HANDOFF Section 4) |

### R2 integration

| Criterion | Verdict | Proving tests |
| --- | --- | --- |
| Diagnosis display and eligibility branch only on the closed state vocabulary | **MET** | `tests/diagnosis/test_conformance_351_352.py::TestR2Integration` (3 tests: every linked evidence state is a closed-vocabulary member; every Evidence Level derives through the total mapping; a finding asserting a level off the mapping is unrepresentable); `tests/capmap/test_render.py::test_evidence_line_wording_is_total_over_the_r2_vocabulary` (the renderer has exactly one wording per R2 state and no other branch), `::TestHonestUnknowns` (instrument failure renders as "couldn't check X because Y"; `absent`/`not-assessed` never read as passing; an Unknown is never dressed as a pass); G6 classifications carry R2 states (`inferred` for evaluated results, `not-assessed` for fail-closed — `tests/taxonomy/test_classifier.py`); the engine's state branching is exercised by `tests/diagnosis/test_engine.py` (staleness degradation, instrument-failure → `blocked`/`unverified`, intentionally-off → `absent`) |

### Jobs-first Capability Map (the HANDOFF 2.3 M-D rendering clause)

| Criterion | Verdict | Proving tests |
| --- | --- | --- |
| Map organized around confirmed jobs, findings nested inside; no flat finding list representable | **MET** | `tests/capmap/test_model.py::TestFindingsNestInsideJobs` (incl. `test_no_flat_system_wide_finding_list_is_representable` — no `CapabilityMap` field admits a `Finding` directly); `tests/diagnosis/test_conformance_351_352.py::TestJobsFirstReportShape`; `tests/capmap/test_render.py::TestJobsFirstStructure` |
| Each finding shows evidence, uncertainty, boundary, practical implication, why-it-matters, one next move; Evidence Level shown for every finding | **MET** | `tests/capmap/test_render.py::test_every_finding_shows_its_evidence_level`, `::test_every_finding_shows_the_full_m_d_surface`; `Finding.recommended_next_move` is singular by construction (`tests/diagnosis/test_finding.py::test_next_move_is_singular_by_construction`) |
| Non-judgmental language; vocabulary compliance (HANDOFF 1.5 "Avoid" terms) | **MET** | `tests/capmap/test_render.py::TestVocabularyCompliance` (scans all rendered output and all R2 state wordings) |
| The person can correct both job definition and supporting evidence | **MET** | `tests/capmap/test_correct.py::TestEvidenceCorrectionsAreUserReported` (9 tests: a correction is a new `user-reported` item, the route cannot claim any other state, the account stays visible, other axes untouched), `::TestACorrectionNeverSilentlyUpgrades` (property test over every prior state combination; a correction never reaches Verified/Supported alone; a Verified finding stays Verified, not more), `::TestJobEditsReenterInspection` (a job edit returns an `Inspection` draft, drops the job's findings from the map, keeps only non-raw references, and nothing on the correction path mints a contract) |

---

## 3. Adversarial probes run for this review, and what they found

Five probe families, 36 probes. Three families found nothing; two found real defects (13 escapes), all fixed test-first in commit `7856cd3`.

### 3.1 Novel G6 evasion phrasings — **12 escapes found and closed (Finding H)**

Fifteen phrasings not in the shipped corpus, including three languages the corpus lacked entirely (Dutch, Italian, Portuguese) and one script the rules cannot read (Japanese). **Twelve classified benign** (`high_impact=False`, basis `no-match`):

- Seven English euphemisms: *"Settle the outstanding invoice…"* (money), *"Zero out the archive folder…"* (deletion), *"Onboard a new teammate onto the shared drive"* (permissions), *"Keep tabs on my sugar levels…"* (health), *"Look over the lease…"* (legal), *"Pass along the roster of everyone…"* (third-party data), *"Fire off a quick note…"* (send — caught only by a lucky `stock` false-positive before the fix).
- Five in uncovered languages: Dutch *verwijder/betaal*, Italian *cancella/inviare*, Portuguese *apagar* — the rules had **zero** phrases for these languages, so any job worded in them was silently benign. That satisfied G6's letter (zero false negatives *on the labeled corpus* — the corpus had no such entries) while missing its intent.

Fixed: per-category rule phrases added for Italian, Dutch, and Portuguese plus the seven English euphemisms; **every escape is now a corpus entry** (171 → 187, languages en/es/fr/de/it/nl/pt/ja), so the zero-false-negative corpus gate pins them forever; regression tests in `TestNovelEvasionsM2Review` assert the specific category, not just the flag. Japanese was already safe — it normalizes to no ASCII words and fails closed as unclassifiable → high-impact — and is now pinned as a corpus entry and a test. The corpus test was amended to accept a **fail-closed catch** (high-impact with no category, basis unclassifiable) for entries in unreadable scripts, while keeping the stricter category-match bar for rule matches: what G6 gates is the routing, and the fail-closed path withdraws automation without naming a category.

**Honest limit named by this finding:** a keyword classifier's multilingual coverage is enumerable, and enumeration is never total — a phrasing in, say, Polish would today reach `no-match` if it contains ≥2 ASCII-transliterable words. See §4.

### 3.2 Aggregate-score smuggling — **one escape family found and closed (Finding I, part 1)**

Four routes: a runtime subclass (`class ScoredFinding(Finding): maturity_score: float` — `typing.final` does not prevent runtime subclassing) instantiated fine but **refused to serialize** (`UninventoriedFieldError`: `ScoredFinding.maturity_score` has no inventory entry — the G2 boundary held); `model_construct` with an extra `aggregate_score=99` silently dropped the field (pydantic ignores unknown keys on that route); **but `Finding.model_construct` and `Finding.model_copy` bypassed the axis-honesty validator entirely**, making a `Working`/`Verified`/`Safe` finding with **zero evidence** representable — the schema docstring's own "unrepresentable" claim was code review, not structure, on those routes. This is the exact class the M1 review closed on `EvidenceItem` (M1 Finding E); the M2 models had not inherited the pattern.

Fixed with the house pattern (override `model_construct`/`model_copy`, re-assert the invariant) on **five models**: `Finding` (axis honesty), `SuccessContract` (the `diagnosis` lifecycle literal — a forged draft-to-confirmed swap now refuses at the type, not only at the engine), `ConfirmedJobExport` (an `InspectionJob` in a share payload now refuses on every construction route — previously `model_construct` accepted one, though `dump_for_transmission` still refused downstream), `JobFindings` (an `Inspection` draft cannot impersonate a confirmed job entry), and `CapabilityMap`. The safe-boundary check now compares by equality rather than identity so a plain-string `"safe"` axis cannot evade it on the skip routes. Tests: `TestValidationBypassRoutes` in `tests/diagnosis/test_finding.py`, `tests/jobs/test_success_contract.py`, `tests/capmap/test_model.py`; `TestShareExclusionBypassRoutes` in `tests/jobs/test_inspection.py` (16 new tests).

### 3.3 `InspectionJob` through every serializer route — **no escape**

`dump_for_transmission` refuses (`NoTransmissibleFieldsError` — no field in the entire product declares sharing at M2); `ConfirmedJobExport` refuses an `InspectionJob` at validation, on `model_construct`, and on `model_copy` (the construct route closed by Finding I); `model_dump`, `model_dump_json`, `dict()`, `TypeAdapter.dump_python`, and `json.dumps` of the dict all succeed **and are lawful**: they are the local-only storage path through the G2 boundary (every stored field inventoried `sharing: never`, deletion path registered). Pickle round-trips the object, but **no product or test code imports pickle** (verified by grep); pickle is not a product serialization surface at M2 — recorded as a residual to re-check when M3 adds a session store (§4).

### 3.4 Unconfirmed jobs into the diagnosis engine — **no escape**

An `InspectionJob`, a field-identical dict, a `SuccessContract` **runtime subclass** (defeats `isinstance`, defeated by the engine's exact-`type()` check), a `model_construct`-forged contract with `lifecycle="inspection"` (now refused by the type itself per Finding I, previously by the engine's lifecycle check — two layers), and an empty confirmation set: all five refused with `DiagnosisInputError`.

### 3.5 Evidence-Level upgrade through corrections — **no escape**

Repeated corrections never move a level past `max(prior, Reported)` (three stacked correction attempts: Unknown → Reported, then stable); a correction on an Unknown-level finding caps at Reported and announces the movement in a visible note; the correction route structurally cannot claim any state but `user-reported` (the function takes no state parameter); a hand-built finding asserting a *lower* level than its evidence derives (laundering headroom for a later "upgrade") is unrepresentable (`ValidationError`: the level is derived, never asserted). The shipped property test `TestACorrectionNeverSilentlyUpgrades::test_over_every_prior_state_combination` covers all prior-state combinations.

---

## 4. PARTIAL / GAP / residual items, stated honestly

| Item | Status | Reason |
| --- | --- | --- |
| **G6 multilingual coverage is enumerated, not total** | **Residual, by construction** | Zero false negatives holds on the labeled corpus (now 8 languages incl. the fail-closed ja path), and unreadable scripts fail closed. But a high-impact job phrased in an *uncovered Latin-script language* (e.g. Polish, Swedish) with ≥2 recognizable words would classify `no-match` → benign today. The gate as written is corpus-relative and MET; the intent is only as strong as the corpus. Options for M3+: grow the corpus per pilot-relevant language, or fail closed on text whose language cannot be affirmatively identified. Carry into the R7 risk register |
| **G6 classification of the D8 decision** | **Bounded residual** | The classifier is fully local/deterministic per the D8 working posture (no model call). If D8 lands on consented cloud-model use for job proposal, the classifier's honesty labels (`inferred`) and the session fail-closed wrapper still apply, but the rule set was designed for a no-model pilot. Revisit at D8 |
| **G6 false positives: 4/36 benign entries misroute** | **Recorded, never gated (by the gate's own design)** | `ben-33..36` (summarize newsletters, draft-replies-for-review, explain legal terms, build a vaccine study guide) hit the send/legal/health stems. All four predate this review; the design bias is explicit: false negatives are the failure mode, false positives cost only automation convenience. Recorded per run via `record_property` |
| **Pickle can serialize domain objects** | **Residual, not a product surface** | No product code imports pickle (verified). The G2 boundary guards pydantic routes, not `__reduce__`. If any future module pickles domain objects (caching, session store at M3), that is an uninventoried persistence path. Add to the M3 checklist and the R7 register |
| **`model_construct` guards are per-model, not automatic** | **Residual pattern risk** | Findings E (M1) and I (M2) are the same defect class appearing on each milestone's new models. Five M2 models are now guarded, but nothing structurally forces the *next* model to inherit the pattern. Worth a small M3 task: a base-class-level re-validation hook or a test that walks every `InventoriedModel` subclass and asserts skip-route guards exist for models with cross-field invariants |
| **Propose–confirm flow is engine-level, not UI-level** | **In scope for M3, not M2** | HANDOFF 2.3 M-C's propose–confirm flow exists as `jobs/propose.py` (proposals are `inferred`-only, canonically ordered, deterministic, and nothing in the module returns a `SuccessContract`) with the confirm exit on the store. The *person-facing* confirm/edit/remove UI is the M3 concierge (journey stage 4). No M2 claim is made about UI |
| **"Approved scope" is honored by construction, not yet re-validated per read** | **In scope for M3 (R3), not M2** | At M2 the engine consumes only the adapter envelope collected under the M1 allowlist; R3's scope-revalidation-per-read-batch is an M3 criterion. No M2 claim is made about it |
| G1, G2 (beyond the boundary's use here), R3, G3, G4, G5, R4–R7, T1–T9, P1 | **Not in scope for M2** | Scheduled M1 (done — see `M1-ACCEPTANCE.md`) and M3–M6 per HANDOFF Section 4 |

---

## 5. Overall M2 verdict

**M2 is MET.** Every listed M2 acceptance criterion — R1 in full, the #351/#352 conformance clause, G6, and R2 integration — has at least one passing, cited test, and the full suite passes in CI on all four matrix legs (run [31192436387](https://github.com/davekilleen/dex-capability-exchange/actions/runs/31192436387), commit `7856cd3`).

This verdict was **not** available when the review began: 13 of 36 adversarial probes escaped. Grounds:

- The adversarial pass found **two defect families**: Finding H (12 G6 evasion escapes — 7 English euphemisms and 5 phrasings in languages the rules had zero coverage for) and Finding I (validation-bypass routes on five M2 models, letting a dishonest Working/Verified/Safe finding, a forged contract lifecycle, and an `Inspection` job inside a share payload be *represented* even where downstream layers still refused to act on them). Both fixed test-first; the suite grew 840 → 869 collected (865 pass locally, 4 darwin-only skips green on the macOS legs).
- Three probe families found nothing: serializer routes for `InspectionJob` (the G2 boundary and the R1 export type held on every path that matters, including `TypeAdapter` and the guarded-serializer last-ditch check), unconfirmed-job injection into the engine (five variants, including an exact-type-evading subclass), and Evidence-Level upgrades through corrections (including multi-step ratcheting and low-ball laundering).
- Defense-in-depth was observed working, not assumed: before the fixes, every Finding-I representation escape was still caught by a *second* layer (`dump_for_transmission`, the engine's lifecycle check, the inventory boundary on the subclass route). The fixes restore the first layer so "unrepresentable" is true as stated, rather than "representable but unusable".

Honest qualifications that should travel with the verdict:

1. **G6's zero-false-negative guarantee is exactly as strong as the labeled corpus.** This review made the corpus meaningfully harder (187 entries, 8 languages, fail-closed script coverage) and the finding is pinned, but enumeration is not totality — the residual is named in §4 and belongs in the R7 risk register with an owner (D7).
2. **Findings E (M1) and I (M2) are one recurring defect class** — pydantic's validation-skip routes versus cross-field invariants. M1's closing recommendation ("rules enforced in two places are single-sourced") did not prevent it recurring on new models. The M3 builder should treat the skip-route guard as part of the definition of any new `InventoriedModel` with a `model_validator`, and the walking-test idea in §4 would make that structural.
3. The M1 review's standing practices held value here: the probe battery re-used its sabotage-first mindset, and the instrument-can-fail discipline (every new test failed before its fix) was applied to all 29 new tests.
4. Nothing here speaks to M3–M6. Per HANDOFF Section 4, real-user automated adaptation still requires all six Fable gates green on the exact pilot build plus R6's red-team — M2 contributes G6 (taxonomy layer) and the R1/R2 machinery only.

**Recommendation:** M2 can be signed off against CI run [31192436387](https://github.com/davekilleen/dex-capability-exchange/actions/runs/31192436387). Carry the §4 residuals into the R7 unresolved-risk register (G6 language coverage, pickle-as-non-surface, skip-route guard pattern), and hand M3 the two standing tasks named there: the `InventoriedModel` skip-route walking test, and the D8-dependent review of G6 posture.
