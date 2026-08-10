#!/usr/bin/env python3
"""Run and record the release-blocking exact pilot-build gate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from capability_exchange.pilot.gate import (  # noqa: E402
    execute_pilot_gate,
    subprocess_gate_runner,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = execute_pilot_gate(
        commit=args.commit,
        observed_at=datetime.now(UTC),
        runner=subprocess_gate_runner,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.dump_for_storage(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(report.explanation)
    print(f"evidence: {args.output}")
    return 0 if report.pilot_start_allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
