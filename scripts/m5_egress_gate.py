#!/usr/bin/env python3
"""Formal exact-byte M5 contribution egress evidence executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_IDS = (
    "tests/concierge/test_contribution_journey.py",
    "tests/egress/test_m5_contribution_egress.py",
)
_UNPROVEN = re.compile(
    r"\b(?:skip|skipped|unproven|not[ -]proven|xfailed|xpassed|deselected)\b|"
    r"\b(?:0|no) tests? (?:collected|ran|run)\b",
    re.IGNORECASE,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commit = os.environ.get("DEX_LENS_BUILD_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("M5 egress gate NOT PROVEN: exact build commit is required")
    live_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    if commit != live_commit:
        raise SystemExit("M5 egress gate NOT PROVEN: build commit does not match HEAD")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", *TEST_IDS],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    proven = completed.returncode == 0 and _UNPROVEN.search(output) is None
    payload = {
        "schema_version": 1,
        "status": "proven" if proven else "not-proven",
        "commit": commit,
        "producer": "scripts/m5_egress_gate.py",
        "proofs": ["formal:m5-egress"],
        "test_ids": list(TEST_IDS),
        "pytest_output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("M5 exact contribution egress PROVEN" if proven else "M5 egress NOT PROVEN")
    return 0 if proven else 1


if __name__ == "__main__":
    raise SystemExit(main())
