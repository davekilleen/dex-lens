from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.adapters.claude_code.discovery import discover_fingerprint
from capability_exchange.adapters.claude_code.snapshot import take_snapshot
from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    HumanCapability,
)
from capability_exchange.diagnosis.observations import EvidenceFingerprint

NOW = datetime(2026, 8, 27, tzinfo=UTC)
CANARY = "INVENTED_EVAL_CANARY_NEVER_RETAIN"

SKILL = """---
name: {name}
description: {description}
---

## Method
{method}
"""

FILES = {
    "CHANGELOG.md": "# Changes\n\n## v0.8.3 — Local Services\n",
    ".mcp.json": json.dumps(
        {
            "mcpServers": {
                "career-data": {"command": "python3", "args": ["role_data_server.py"]},
                "calendar-data": {"url": "https://example.invalid/mcp"},
                "project-data": {"command": "node"},
                "writing-data": {"command": "python3"},
                "research-data": {"command": "python3"},
            }
        }
    ),
    ".claude/settings.json": json.dumps(
        {
            "mcpServers": {
                "career-data": {
                    "command": "python3",
                    "env": {"API_TOKEN": CANARY},
                },
                "work-data": {"command": "node"},
                "notes-data": {"command": "python3"},
            },
            "hooks": {"SessionStart": [{"command": f"runner --token {CANARY}"}]},
        }
    ),
    ".scripts/nightly-check.sh": "#!/bin/sh\nexit 0\n",
    ".scripts/install-nightly-check.sh": "#!/bin/sh\nexit 0\n",
    ".scripts/nightly-check.plist.template": "<plist><dict></dict></plist>\n",
    "Library/LaunchAgents/org.invented.nightly-check.plist": (
        "<plist><dict><key>Label</key><string>org.invented.nightly-check</string>"
        "<key>StartCalendarInterval</key><dict/></dict></plist>\n"
    ),
    "Library/LaunchAgents/org.invented.changelog-check.plist": (
        "<plist><dict><key>Label</key><string>org.invented.changelog-check</string>"
        "<key>StartCalendarInterval</key><dict/></dict></plist>\n"
    ),
    "System/system-doctor.py": "def check():\n    return {'state': 'unknown'}\n",
    "core/mcp/role_data_server.py": "def list_tools():\n    return ['private_tool']\n",
    "System/integrations/registry.json": json.dumps(
        {"providers": {"calendar": {}, "work": {}}}
    ),
    "System/integrations/config.yaml": "providers:\n  calendar:\n    enabled: true\n",
    "skills/career-coach/SKILL.md": SKILL.format(
        name="career-coach",
        description="Keep role evidence and next-step reflection together.",
        method="Review evidence with the person before suggesting the next experiment.",
    ),
    "skills/role-plan-custom/SKILL.md": SKILL.format(
        name="role-plan-custom",
        description="Make a plan specific to the role being pursued.",
        method="Tie each action to one role outcome and one dated check-back.",
    ),
    "skills/review-suggestions-custom/SKILL.md": SKILL.format(
        name="review-suggestions-custom",
        description="Keep proposed changes under human review.",
        method="Show the suggestion first and wait for an explicit yes.",
    ),
    "skills/follow-through-custom/SKILL.md": SKILL.format(
        name="follow-through-custom",
        description="Check whether agreed work actually landed.",
        method="Re-open the destination and verify the promised result.",
    ),
}


def write_legacy_system(root: Path) -> EvidenceFingerprint:
    root.mkdir()
    for relative, content in FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    contract = claude_code_contract((str(root.resolve()),))
    allowlist = CanonicalAllowlist(contract.read_scope, denied_paths=contract.denied_paths)
    snapshot = take_snapshot(allowlist, taken_at=NOW)
    return discover_fingerprint(snapshot, collected_at=NOW)


def complete_ledger() -> ComparisonLedger:
    capabilities = (
        HumanCapability(
            capability_id="career-development-loop",
            title="Career development loop",
            job_ids=("develop-career",),
            catalogue_ids=("career-development",),
            person_observation_ids=("skill:career-coach",),
        ),
        HumanCapability(
            capability_id="role-specific-planning-loop",
            title="Role-specific planning loop",
            job_ids=("plan-work",),
            catalogue_ids=(),
            person_observation_ids=("skill:role-plan-custom",),
        ),
        HumanCapability(
            capability_id="human-reviewed-suggestions",
            title="Human-reviewed suggestions",
            job_ids=("keep-human-control",),
            catalogue_ids=(),
            person_observation_ids=("skill:review-suggestions-custom",),
        ),
        HumanCapability(
            capability_id="follow-through-safety-net",
            title="Follow-through safety net",
            job_ids=("verify-outcomes",),
            catalogue_ids=("current-system-health", "verified-backup-restore"),
            person_observation_ids=("skill:follow-through-custom",),
        ),
    )
    entries = (
        CatalogueDisposition(
            catalogue_id="current-system-health",
            disposition=Disposition.WORTH_BORROWING,
            capability_id="follow-through-safety-net",
            evidence_references=("file-token:system-doctor",),
            reason="The local check is implemented but no active outcome is established.",
        ),
        CatalogueDisposition(
            catalogue_id="verified-backup-restore",
            disposition=Disposition.WORTH_BORROWING,
            capability_id="follow-through-safety-net",
            evidence_references=("probe-token:no-restore-proof",),
            reason="No restore proof was observed in the approved evidence.",
        ),
        CatalogueDisposition(
            catalogue_id="career-development",
            disposition=Disposition.SHARED,
            capability_id="career-development-loop",
            evidence_references=("file-token:career-method",),
            method_compared=True,
            reason="Both methods review role evidence before proposing the next experiment.",
        ),
    )
    return ComparisonLedger(
        catalogue_version=5,
        catalogue_sha256="a" * 64,
        capabilities=capabilities,
        entries=entries,
        reciprocal_answer=(
            "Dex should borrow the explicit role-outcome and dated check-back pairing."
        ),
    )


def original_failure_ledger() -> ComparisonLedger:
    complete = complete_ledger()
    entries = tuple(
        item.model_copy(
            update={
                "disposition": Disposition.NOT_ASSESSED,
                "evidence_references": (),
                "method_compared": False,
                "reason": "A matching name was treated as sufficient evidence.",
            }
        )
        if item.catalogue_id == "career-development"
        else item
        for item in complete.entries
    )
    return complete.model_copy(update={"entries": entries, "reciprocal_answer": "Unknown"})
