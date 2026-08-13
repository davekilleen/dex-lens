#!/usr/bin/env python3
"""Fail closed unless a Section-6 run is bound to the reviewed Git commit."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class BuildIdentityError(RuntimeError):
    """The checked-out build cannot prove its source/execution relationship."""


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=repo_root,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except subprocess.CalledProcessError as error:
        detail = error.output.strip() or "git command failed"
        raise BuildIdentityError(detail) from error


def verify_build_identity(
    *,
    event_name: str,
    source_commit: str,
    execution_commit: str,
    repo_root: Path,
) -> tuple[str, str]:
    """Verify the reviewed source and actually checked-out execution commits."""
    if not _GIT_SHA.fullmatch(source_commit):
        raise BuildIdentityError("reviewed source commit must be an exact lowercase Git SHA")
    if not _GIT_SHA.fullmatch(execution_commit):
        raise BuildIdentityError("execution commit must be an exact lowercase Git SHA")

    checked_out_commit = _git(repo_root, "rev-parse", "HEAD")
    if checked_out_commit != execution_commit:
        raise BuildIdentityError(
            "checked-out commit does not match the workflow execution commit"
        )

    if event_name == "pull_request":
        commit_and_parents = _git(
            repo_root, "rev-list", "--parents", "-n", "1", execution_commit
        ).split()
        if len(commit_and_parents) != 3 or commit_and_parents[2] != source_commit:
            raise BuildIdentityError(
                "PR execution commit second parent does not match the reviewed source commit"
            )
    elif event_name == "workflow_dispatch":
        if source_commit != execution_commit:
            raise BuildIdentityError(
                "dispatched source commit does not match the execution commit"
            )
    else:
        raise BuildIdentityError(f"unsupported Section-6 event: {event_name!r}")

    return source_commit, execution_commit


def main() -> int:
    try:
        source_commit, execution_commit = verify_build_identity(
            event_name=os.environ.get("DEX_LENS_EVENT_NAME", ""),
            source_commit=os.environ.get("DEX_LENS_SOURCE_COMMIT", ""),
            execution_commit=os.environ.get("DEX_LENS_BUILD_COMMIT", ""),
            repo_root=Path.cwd(),
        )
    except BuildIdentityError as error:
        print(f"SECTION6 BUILD IDENTITY FAILED: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "execution_commit": execution_commit,
                "source_commit": source_commit,
                "status": "bound",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
