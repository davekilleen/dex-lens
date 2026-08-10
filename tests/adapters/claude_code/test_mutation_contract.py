from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adaptation.contract import REQUIRED_GUARANTEES, OperationKind
from capability_exchange.adaptation.hosts.claude_code import (
    build_claude_code_skill_preview,
    claude_code_adaptation_contract,
    claude_code_mutation_contract,
)
from capability_exchange.adapter import AdapterMode
from capability_exchange.adapters.claude_code.contract import claude_code_contract

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def test_read_only_contract_remains_diagnose_only_by_default(tmp_path: Path) -> None:
    contract = claude_code_contract((str(tmp_path),))
    assert contract.mode is AdapterMode.DIAGNOSE_ONLY
    assert contract.mutation_contract is None


def test_adaptation_contract_is_explicit_complete_and_closed(tmp_path: Path) -> None:
    contract = claude_code_adaptation_contract((str(tmp_path),))
    assert contract.mode is AdapterMode.ADAPT_CAPABLE
    assert contract.mutation_contract == claude_code_mutation_contract()
    assert contract.mutation_contract.operations == (
        OperationKind.CREATE_NAMESPACED_SKILL,
    )
    assert contract.mutation_contract.guarantees == REQUIRED_GUARANTEES


def test_host_recipe_builds_one_create_only_standard_markdown_preview(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    preview = build_claude_code_skill_preview(
        approved_skills_root=skills_root,
        job_id="reading-list",
        capability_id="topic-grouping",
        markdown="# Reading list\n\nGroup new entries by topic.\n",
        expected_benefit="Group reading-list entries by topic",
        created_at=NOW,
    )
    assert Path(preview.target_path) == skills_root / "dex-lens-reading-list.md"
    assert preview.effects == (f"create-file:{preview.target_path}",)
    assert preview.content.startswith("# Reading list")


def test_mutation_code_is_not_exported_on_diagnosis_adapter_surface() -> None:
    import capability_exchange.adapter as diagnosis_adapter
    import capability_exchange.adapters.claude_code as read_only_adapter

    for surface in (diagnosis_adapter, read_only_adapter):
        assert not hasattr(surface, "build_claude_code_skill_preview")
        assert not hasattr(surface, "TransactionEngine")

