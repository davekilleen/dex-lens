# Dex Lens

The working agreement for this repository lives in `AGENTS.md` — the job in
one paragraph, the acceptance bar a real stale install sets, and the failure
ledger of how we have actually been wrong. Read it before touching
comparison, authorship, coverage, or the report.

@AGENTS.md

## Claude-specific notes

- **Plain words, always — founder's standing instruction (2026-09-07).** No
  invented metaphors ("loan", "presence is the claim"), no codenames, no
  insider shorthand — not in anything a Lens user reads, and not in
  explanations to Dave. Explain a mechanism as: which file, which check, what
  it decides, what a person sees. If a sentence needs decoding, rewrite it
  before sending it.

- `python3` on the PATH lacks this project's dependencies. Use
  `.venv/bin/python` for anything importing `capability_exchange`, including
  `scripts/check_inventory.py`. The path is relative to the repository root,
  so `cd` there first.
- Every changed test file gets run alone as well as in the suite —
  `.venv/bin/python -m pytest tests/path/to/test_file.py` — because
  suite-order coupling has hidden real failures here before.
- A session that intends to change behaviour starts by reading
  `docs/RISK-REGISTER.md`. Zero open rows is the steady state; a new open row
  is how work-in-progress is recorded, not a TODO comment.
