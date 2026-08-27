# Task 11 code-quality review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice.

## What was reviewed

- `src/capability_exchange/skill/dex-lens/SKILL.md`
- `tests/test_skill_complete_diagnosis.py`
- `tests/test_skill_deterministic_engine.py`
- `tests/test_skill_report_template.py` (unchanged; still green)

Specification review already passed.

## Invariants that hold

- The assistant follows `diagnosis status` / `advance` / `submit` /
  `result`. It does not keep a private checklist or rewrite catalogue
  totals.
- A diagnosis ends only when the engine returns `closed`.
- Repairs, install, share, and send require a separate, explicitly
  approved flow. A preview is not a share receipt.
- Every generated close field from the design is named in the skill.
- Consent, read-only, praise, reciprocity, three-or-fewer, evidence
  labels, and the two-way comparison rubric remain.
- The report template markdown fence, `dex-lens reports check`, and
  “refuses a report that has not shown its work” remain, so the save
  gate and the skill still agree.
- No independent numeric coverage examples. `Never invent a score.`
  stays.

## Residual notes, not blocking

- The skill still teaches the assistant how to read and explain a
  system. That is intentional. The engine owns the books; the assistant
  still has to speak plainly.
- Diagnosis CLI/MCP adapters are later tasks. This slice only changes
  what the skill tells the assistant to follow.

## Continue

Later tasks: adapters, specialists, and golden replay. Do not weaken
the skill’s engine-truth contract while those land.
