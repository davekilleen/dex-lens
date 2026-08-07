"""The shipped Claude Code contract declaration: Diagnose-only, coherent."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_exchange.adapter import (
    AdapterMode,
    ArchivePolicy,
    SymlinkPolicy,
    VersionDetectionMethod,
)
from capability_exchange.adapters.claude_code.contract import (
    CLAUDE_CODE_ADAPTER_ID,
    CLAUDE_CODE_EVIDENCE_PROBES,
    GLOBALLY_DENIED_PATHS,
    claude_code_contract,
)


def test_contract_builds_and_is_diagnose_only(claude_root: Path) -> None:
    contract = claude_code_contract([str(claude_root)])
    assert contract.adapter_id == CLAUDE_CODE_ADAPTER_ID
    assert contract.mode is AdapterMode.DIAGNOSE_ONLY
    assert contract.mutation_contract is None


def test_denied_paths_cover_credential_homes(claude_root: Path) -> None:
    contract = claude_code_contract([str(claude_root)])
    for denied in GLOBALLY_DENIED_PATHS:
        assert denied in contract.denied_paths
    assert f"{claude_root}/.credentials.json" in contract.denied_paths
    assert f"{claude_root}/.claude/.credentials.json" in contract.denied_paths


def test_containment_policies_are_the_safe_members(claude_root: Path) -> None:
    contract = claude_code_contract([str(claude_root)])
    assert contract.symlink_policy is SymlinkPolicy.RESOLVE_AND_REJECT_ESCAPES
    assert contract.archive_policy is ArchivePolicy.DO_NOT_OPEN
    assert contract.version_detection is VersionDetectionMethod.FILE_MARKER


def test_probes_match_the_collector_implementation(claude_root: Path) -> None:
    contract = claude_code_contract([str(claude_root)])
    assert contract.evidence_probes == CLAUDE_CODE_EVIDENCE_PROBES


def test_duplicate_roots_are_collapsed(claude_root: Path) -> None:
    contract = claude_code_contract([str(claude_root), str(claude_root)])
    assert contract.discoverable_roots == (str(claude_root),)


def test_relative_root_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="absolute"):
        claude_code_contract(["relative/path"])


def test_whole_filesystem_root_refused() -> None:
    with pytest.raises(ValidationError):
        claude_code_contract(["/"])
