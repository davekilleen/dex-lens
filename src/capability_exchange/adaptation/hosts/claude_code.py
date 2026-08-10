"""Claude Code's explicit create-only M4 mutation contract and recipe."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.contract import (
    REQUIRED_GUARANTEES,
    MutationContract,
    OperationKind,
)
from capability_exchange.adaptation.preview import AdaptationPreview, build_preview
from capability_exchange.adapter import AdapterContract, AdapterMode
from capability_exchange.adapters.claude_code.contract import claude_code_contract

__all__ = [
    "build_claude_code_skill_preview",
    "claude_code_adaptation_contract",
    "claude_code_mutation_contract",
]

_JOB_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def claude_code_mutation_contract() -> MutationContract:
    """The one M4 host contract; declarations still need T1–T9 evidence."""

    return MutationContract(
        contract_id="claude-code-local-mutation",
        contract_version="1.0.0",
        operations=(OperationKind.CREATE_NAMESPACED_SKILL,),
        guarantees=REQUIRED_GUARANTEES,
    )


def claude_code_adaptation_contract(
    approved_roots: Sequence[str],
) -> AdapterContract:
    """Opt in to Adapt-capable explicitly; the normal adapter stays read-only."""

    base = claude_code_contract(approved_roots)
    return base.model_copy(
        update={
            "mode": AdapterMode.ADAPT_CAPABLE,
            "mutation_contract": claude_code_mutation_contract(),
        }
    )


def build_claude_code_skill_preview(
    *,
    approved_skills_root: Path,
    job_id: str,
    capability_id: str,
    markdown: str,
    expected_benefit: str,
    created_at: datetime,
) -> AdaptationPreview:
    """Preview one namespaced, user-owned, standard Markdown skill file."""

    if not _JOB_ID.fullmatch(job_id):
        raise ValueError("job_id must be kebab-case before it can name a local file")
    if not markdown.startswith("# "):
        raise ValueError("the create-only skill must be standard Markdown with a heading")
    request = OperationRequest(
        operation=OperationKind.CREATE_NAMESPACED_SKILL,
        approved_root=str(approved_skills_root),
        relative_path=f"dex-lens-{job_id}.md",
    )
    return build_preview(
        request=request,
        host_id="claude-code-local",
        job_id=job_id,
        capability_id=capability_id,
        content=markdown,
        expected_benefit=expected_benefit,
        created_at=created_at,
    )

