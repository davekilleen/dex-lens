# Task 11 specification review

**Date:** 2026-08-27
**Verdict:** Pass for the scoped slice. Implement only after the new tests fail.

## Scope under review

Move the Dex Lens skill from orchestration to explanation.

- Rewrite `src/capability_exchange/skill/dex-lens/SKILL.md` so the
  assistant follows engine `status` / `advance` / `submit` / `result`
- Keep consent, read-only, praise, two-way comparison, and evidence rules
- Keep the report template that `reports check` already enforces
- Do not implement Python engine, CLI, MCP, receipts, or specialists
- Do not change the installer or version

## Contract the tests lock

1. The skill names `dex-lens diagnosis status` and forbids the assistant
   from calculating or rewriting catalogue totals.
2. A diagnosis ends only when the engine returns `closed`.
3. Repairs, install, share, and send require the assistant to start a
   separate, explicitly approved flow. A preview is not a share receipt.
4. The skill names every generated close field from the design /
   `ReportModel` close:
   the strongest grounded thing already doing; what Dex should learn, or
   the honest empty answer; the single best first move if one cleared the
   bar; where the report was saved; how to return to the run; and the
   separate sharing and future-watch choices.
5. The skill keeps `Never invent a score.` and carries no independent
   numeric coverage examples such as `93 covered` or `7/10`.
6. Product invariants stay: name match is not proof; version distance;
   MCP server is not its tool list; written is not running; praise and
   reciprocity; at most three recommendations; unavailable entries cannot
   be recommended.
7. `test_skill_report_template.py` still finds a markdown report
   template, `dex-lens reports check`, and the sentence that the save
   path refuses a report that has not shown its work.

## Out of scope

- Python diagnosis engine, CLI adapter, MCP adapter, receipts, specialists
- Installer registration and version bumps
- Changing the report-save gate itself
