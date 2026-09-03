#!/usr/bin/env python3
"""Grade one closed Lens diagnosis without printing private proposal text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from capability_exchange.diagnosis.comparison import ComparisonLedger
from capability_exchange.diagnosis.work import WorkAudit
from capability_exchange.diagnosis.wow_gate import grade_wow_run


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grade one closed Lens Wow Gate run.")
    parser.add_argument("--result", required=True, help="closed result JSON path")
    parser.add_argument(
        "--audit",
        help=(
            "optional work audit JSON path, cross-checked against the audit the "
            "ledger was closed with; the ledger's own audit is what grades"
        ),
    )
    parser.add_argument("--output", required=True, help="aggregate grade JSON output path")
    args = parser.parse_args(argv)

    try:
        result_payload = _load_json(Path(args.result))
    except (OSError, ValueError) as exc:
        # Never render the exception: a malformed result file repeats its own
        # content, and that content is the inspected system's.
        print(f"result JSON could not be read: {type(exc).__name__}", file=sys.stderr)
        return 2
    ledger_payload = result_payload.get("ledger")
    if not isinstance(ledger_payload, dict):
        print("result JSON must contain a ledger object", file=sys.stderr)
        return 2
    try:
        ledger = ComparisonLedger.model_validate(ledger_payload)
        audit = WorkAudit.model_validate(_load_json(Path(args.audit))) if args.audit else None
        grade = grade_wow_run(ledger, audit)
    except (OSError, ValueError) as exc:
        print(f"this run could not be graded: {type(exc).__name__}", file=sys.stderr)
        return 2
    output = {
        "score": grade.score,
        "passed": grade.passed,
        "hard_failure_count": len(grade.hard_failures),
        # Names only. Each is a fixed slug from a closed vocabulary, so a
        # failing gate is actionable without re-running the grader in Python
        # and without carrying anything from the inspected system.
        "hard_failures": list(grade.hard_failures),
        "dimensions": {
            "significant_coverage": grade.significant_coverage,
            "workflow_quality": grade.workflow_quality,
            "recommendation_quality": grade.recommendation_quality,
            "reciprocal_quality": grade.reciprocal_quality,
            "evidence_integrity": grade.evidence_integrity,
            "autonomy_and_clarity": grade.autonomy_and_clarity,
        },
    }
    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if grade.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
