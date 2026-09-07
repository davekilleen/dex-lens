"""An invented vault carrying the structural properties of a *stale* install.

`legacy_system_fixture` is a twenty-file diorama with a clean three-line
changelog, and it has never produced the failure modes a genuinely old
install produces.  This fixture exists because a real run against an install
left alone for months missed a ten-release gap while every gate was green
(AGENTS.md F6).  Its job is to carry, in invented content, the properties
listed in AGENTS.md §2:

* thousands of files, not dozens;
* a hundred-plus skills mixing four authorship situations that a stale
  install genuinely contains — capability the current catalogue still names,
  capability Dex shipped under a name the current catalogue has dropped,
  assistant-vendored material, and the person's own work;
* dozens of hooks, all of them under a path Dex's own contract claims;
* a ``CHANGELOG.md`` whose ``[Unreleased]`` section is long enough to push
  the first version header down the file, because an install nobody has
  updated accumulates unreleased notes;
* no ``.dex-version`` file, because no real install has ever carried one;
* ``core/provision-contract.json`` — Dex's own declarative ownership map,
  shipped alongside the files it describes and therefore present at *any*
  install age.

Every name, path and word here is invented.  Nothing is copied from, derived
from, or measured against any real person's system.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.adapters.claude_code.discovery import discover_fingerprint
from capability_exchange.adapters.claude_code.snapshot import take_snapshot
from capability_exchange.diagnosis.observations import EvidenceFingerprint

NOW = datetime(2026, 9, 7, 9, tzinfo=UTC)

#: The release this invented install identifies as. Every capability in the
#: catalogue fixtures post-dates it, which is the stale-install condition.
INSTALLED_RELEASE = "v1.4.0"

SKILL = """---
name: {name}
description: {description}
model_hint: balanced
---

# {title}

{description}

## Process

{method}
"""

#: Capability the *current* catalogue still names. A run must call these Dex's
#: own and never praise them back at their vendor.
CURRENT_STOCK_SKILLS = ("workflow-skill", "dormant-helper")

#: Capability Dex shipped under a name the current catalogue has since
#: dropped. This is the population that broke the authorship axis: absent
#: from today's catalogue, and therefore read as the person's own work.
RETIRED_STOCK_SKILLS = (
    "vault-doctor",
    "vault-push",
    "vault-status",
    "beta-enrol",
    "beta-state",
    "diff-notes",
    "capability-listing",
    "demo-walkthrough",
    "demo-cleanup",
    "session-close",
    "session-open",
    "session-rescue",
    "system-refresh",
    "provider-connect",
    "provider-sync",
)

#: Assistant-vendored material. Neither the person's strength nor a fact
#: about their install.
VENDORED_SKILLS = (
    "anthropic-pdf",
    "anthropic-docx",
    "anthropic-xlsx",
    "anthropic-pptx",
    "anthropic-skill-creator",
)

#: The person's own work, written under the one path Dex's contract carves out
#: as user-owned.
AUTHORED_CUSTOM_SKILLS = (
    "deal-review-custom",
    "week-shaping-custom",
    "follow-through-custom",
    "thinking-partner-custom",
)

#: The person's own work written *beside* Dex's, under a name that follows the
#: obvious convention rather than the blessed one. Dex's contract claims this
#: path, so no local signal separates these from retired stock — the honest
#: classification is "unattributed", and pretending otherwise in either
#: direction is a defect.
AUTHORED_IN_OWNED_TREE = (
    "deal-brief-mine",
    "quarter-shaping-mine",
    "inbox-shaping-mine",
)

PROVISION_CONTRACT: dict[str, object] = {
    "version": 1,
    "description": (
        "Declarative ownership and bootstrap contract for vault provisioning. "
        "More-specific rules take precedence over broader directory rules."
    ),
    "ownership": {
        "shipped": [
            ".agents/",
            ".claude/",
            "CHANGELOG.md",
            "CLAUDE.md",
            "README.md",
            "System/",
            "core/",
            "docs/",
            "install.sh",
            "package.json",
        ],
        "mergeable-config": [".mcp.json"],
        "user-owned": [
            "00-Inbox/",
            "04-Projects/",
            "05-Areas/",
            "06-Resources/",
            "System/user-profile.yaml",
            ".claude/skills/*-custom/",
            ".agents/skills/*-custom/",
        ],
        "generated": ["core/paths.json", "System/.dex/"],
    },
}


def _changelog(unreleased_notes: int) -> str:
    """A changelog shaped like one nobody has updated in months.

    ``unreleased_notes`` controls how far down the file the first version
    header sits. An install left alone accumulates these, and the release
    detector reads only the head of the file — so the count is the axis of a
    real defect, not decoration.
    """

    lines = [
        "# Changelog",
        "",
        "All notable changes to Dex will be documented in this file.",
        "",
        "## [Unreleased]",
        "",
    ]
    for index in range(unreleased_notes):
        lines += [
            f"### Improvement {index + 1}",
            "",
            "An invented note describing work that has not been released.",
            "",
        ]
    lines += [
        f"## {INSTALLED_RELEASE} — Invented Release ({NOW:%Y-%m-%d})",
        "",
        "The release this invented install identifies as.",
        "",
    ]
    return "\n".join(lines)


def _own_changelog() -> str:
    """A changelog belonging to the person, carrying none of Dex's markers."""

    return (
        "# Changelog\n\n"
        "Notes I keep about my own system.\n\n"
        "## Recent\n\n"
        "- Reorganised my daily notes.\n"
    )


def _skill_files(name: str, *, directory: str) -> tuple[str, str]:
    return (
        f"{directory}/{name}/SKILL.md",
        SKILL.format(
            name=name,
            title=name.replace("-", " ").title(),
            description=f"An invented capability recorded under the name {name}.",
            method="Read the approved evidence, then report what it supports.",
        ),
    )


def stale_install_files(
    *,
    unreleased_notes: int = 6,
    hook_count: int = 45,
    note_count: int = 0,
    dex_present: bool = True,
) -> dict[str, str]:
    """The invented file tree, as relative path to content.

    ``unreleased_notes`` at its default keeps the first version header inside
    the release detector's read window; raise it to push the header out and
    exercise the detection boundary. ``note_count`` inflates the user-owned
    side of the tree towards a realistic file count for tests that care about
    scale rather than classification.

    ``dex_present=False`` builds the same system with Dex never installed: no
    lineage file of any kind, and a changelog that is the person's own rather
    than Dex's. Everything else stays, deliberately including a skill whose
    name collides with a signed capability id — a coincidence a real assistant
    user is very likely to own, and the one that must not be mistaken for
    evidence that Dex is present (AGENTS.md F8).
    """

    files: dict[str, str] = {
        "CHANGELOG.md": (
            _changelog(unreleased_notes) if dex_present else _own_changelog()
        ),
        "core/provision-contract.json": json.dumps(PROVISION_CONTRACT, indent=2),
        "core/paths.py": "VAULT_ROOT = '.'\n",
        "System/user-profile.yaml": "name: an invented person\n",
        ".mcp.json": json.dumps(
            {
                "mcpServers": {
                    "dex-work-mcp": {"command": "python3", "args": ["-m", "work"]},
                    "notes-mine": {"command": "node", "args": ["notes.js"]},
                }
            }
        ),
    }

    if not dex_present:
        # Dex's own declarative artefacts go with it; the person's system
        # remains, collision and all.
        del files["core/provision-contract.json"]
        del files["core/paths.py"]

    for name in (
        *CURRENT_STOCK_SKILLS,
        *RETIRED_STOCK_SKILLS,
        *VENDORED_SKILLS,
        *AUTHORED_IN_OWNED_TREE,
    ):
        path, content = _skill_files(name, directory=".claude/skills")
        files[path] = content
    for name in AUTHORED_CUSTOM_SKILLS:
        path, content = _skill_files(name, directory=".claude/skills")
        files[path] = content

    for index in range(hook_count):
        files[f".claude/hooks/invented-hook-{index + 1:02d}.cjs"] = (
            "module.exports = () => ({ ok: true });\n"
        )

    for index in range(note_count):
        files[f"04-Projects/Invented_Project_{index + 1:04d}/notes.md"] = (
            f"# Invented project {index + 1}\n\nNothing real is recorded here.\n"
        )

    return files


def write_stale_install(
    root: Path,
    *,
    unreleased_notes: int = 6,
    hook_count: int = 45,
    note_count: int = 0,
    dex_present: bool = True,
) -> EvidenceFingerprint:
    """Write the invented install under ``root`` and capture it."""

    root.mkdir(parents=True, exist_ok=True)
    for relative, content in stale_install_files(
        unreleased_notes=unreleased_notes,
        hook_count=hook_count,
        note_count=note_count,
        dex_present=dex_present,
    ).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    contract = claude_code_contract((str(root.resolve()),))
    allowlist = CanonicalAllowlist(
        contract.read_scope, denied_paths=contract.denied_paths
    )
    snapshot = take_snapshot(allowlist, taken_at=NOW)
    return discover_fingerprint(snapshot, collected_at=NOW)
