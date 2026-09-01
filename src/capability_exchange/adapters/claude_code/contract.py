"""The Claude Code deep adapter's shipped contract declaration (HANDOFF M-A).

The first deep adapter targets local, folder-based Claude Code on macOS
(#350) with a Linux-testable abstraction. The declaration here is narrowed
at consent time to the person's actual approved folders — the contract
factory takes the concrete roots the person approved and produces the
versioned :class:`~capability_exchange.adapter.AdapterContract` the
conformance suite holds the adapter to.

Diagnose-only by default: callers must explicitly opt into the separate M4
create-only host mutation contract after its T1–T9 release evidence passes.
"""

from __future__ import annotations

from collections.abc import Sequence

from capability_exchange.adapter import (
    AdapterContract,
    ArchivePolicy,
    SymlinkPolicy,
    VersionDetectionMethod,
)

__all__ = [
    "AUTOMATION_SUFFIXES",
    "CLAUDE_CODE_ADAPTER_ID",
    "CLAUDE_CODE_CATALOGUE_HOST_ADAPTER",
    "CLAUDE_CODE_CONTRACT_VERSION",
    "CLAUDE_CODE_DIAGNOSTIC_BASENAMES",
    "CLAUDE_CODE_EVIDENCE_PROBES",
    "GLOBALLY_DENIED_PATHS",
    "INTEGRATION_BASENAMES",
    "MCP_CONFIG_BASENAMES",
    "RELEASE_BASENAMES",
    "claude_code_contract",
    "is_mcp_manifest_path",
]

CLAUDE_CODE_ADAPTER_ID = "claude-code-local"
CLAUDE_CODE_CONTRACT_VERSION = "0.1.0"

#: The host family this adapter implements, as the signed catalogue names it.
#:
#: Two different identifiers that are easy to conflate. The adapter id above
#: names *this implementation* — local, folder-based, read-only. A catalogue
#: entry's ``compatibility.host_adapters`` names the *host* a capability can
#: live in, and Dex Core publishes that as ``claude-code``. Comparing the
#: implementation id against the host family made the check fail for every
#: entry in the catalogue, so a shelf built from a catalogue that fully
#: supports the person's host told them, 55 times over, that their host was
#: not listed.
CLAUDE_CODE_CATALOGUE_HOST_ADAPTER = "claude-code"

#: Probe ids the collector implements; the contract declares exactly these.
CLAUDE_CODE_EVIDENCE_PROBES: tuple[str, ...] = (
    "collection-exclusions",
    "installation-shape",
    "instructions-present",
    "settings-present",
    "skills-present",
)

MCP_CONFIG_BASENAMES: frozenset[str] = frozenset(
    {
        ".mcp.json",
        "mcp.json",
        "mcp-servers.json",
        "settings.json",
        ".claude.json",
        "config.toml",
    }
)
AUTOMATION_SUFFIXES: frozenset[str] = frozenset({".plist", ".cron", ".service", ".timer"})
INTEGRATION_BASENAMES: frozenset[str] = frozenset(
    {"registry.json", "config.yaml", "config.yml"}
)
RELEASE_BASENAMES: frozenset[str] = frozenset({"CHANGELOG.md", "VERSION", ".dex-version"})


def is_mcp_manifest_path(relative_path: str) -> bool:
    """Recognise reviewed Claude MCP manifest shapes without widening scope."""

    parts = tuple(part.lower() for part in relative_path.replace("\\", "/").split("/") if part)
    if not parts:
        return False
    if parts[-1] in MCP_CONFIG_BASENAMES:
        return True
    return (
        len(parts) >= 3
        and parts[-3:-1] == (".claude", "mcp")
        and parts[-1].endswith(".json")
    )

#: File names the diagnosis reads: the probes' inputs plus the instruction
#: files of the other assistants a real system is built with.
#:
#: This does **not** widen the approved scope — it orders capture inside it.
#: An approved root is often a whole working folder, so the admitted set can
#: be two orders of magnitude larger than the diagnosis needs; on a real
#: 151k-file vault the file-count bound was exhausted before most of these
#: were reached, and the presence probes then reported on an arbitrary
#: fraction of the scope. Capturing declared names first makes the bound bite
#: on material the diagnosis does not use.
#:
#: ``AGENTS.md`` is here because personal AI systems are rarely one-harness:
#: the same setup carries Claude Code instructions AND the AGENTS.md that
#: Codex and Cursor read, often as paired copies of the same intent. An
#: inventory blind to one half cannot see the drift between them — and on
#: the reference vault that drift is one of the largest real findings.
#:
#: ``.mcp.json`` is here because the MCP servers a person wired into their
#: assistant are as much a part of their system as their skills, and the
#: inventory was blind to all of them. Its capture is *doubly* load-bearing:
#: an ``.mcp.json`` routinely carries API keys and tokens inside a server's
#: ``env`` block, so naming it as a captured file is what routes it through
#: the same collection-time secret redaction as everything else — the server
#: names are surfaced, the keys never are.
CLAUDE_CODE_DIAGNOSTIC_BASENAMES: frozenset[str] = frozenset(
    {
        *MCP_CONFIG_BASENAMES,
        *INTEGRATION_BASENAMES,
        *RELEASE_BASENAMES,
        "AGENTS.md",
        "CLAUDE.md",
        "SKILL.md",
        "crontab",
        "crontab.txt",
    }
)

#: Never read, whatever the approved scope: credential and key material
#: homes. Declared on every instantiated contract (G1 item d).
GLOBALLY_DENIED_PATHS: tuple[str, ...] = (
    "~/.aws",
    "~/.gnupg",
    "~/.kube",
    "~/.netrc",
    "~/.ssh",
)

#: Credential files Claude Code itself keeps inside its config folder;
#: denied relative to every approved root.
_ROOT_RELATIVE_DENIALS: tuple[str, ...] = (
    ".credentials.json",
    ".claude/.credentials.json",
)


def claude_code_contract(approved_roots: Sequence[str]) -> AdapterContract:
    """The versioned contract, narrowed to the person's approved roots.

    ``approved_roots`` are the concrete folders the person approved at
    consent time (absolute or home-anchored). Validation is delegated to
    :class:`AdapterContract`, which refuses ``/``, ``~``, traversals, and
    scope entries outside the declared roots.
    """
    roots = tuple(dict.fromkeys(approved_roots))
    denied = list(GLOBALLY_DENIED_PATHS)
    for root in roots:
        for relative in _ROOT_RELATIVE_DENIALS:
            denied.append(f"{root.rstrip('/')}/{relative}")
    return AdapterContract(
        adapter_id=CLAUDE_CODE_ADAPTER_ID,
        contract_version=CLAUDE_CODE_CONTRACT_VERSION,
        discoverable_roots=roots,
        read_scope=roots,
        denied_paths=tuple(dict.fromkeys(denied)),
        symlink_policy=SymlinkPolicy.RESOLVE_AND_REJECT_ESCAPES,
        archive_policy=ArchivePolicy.DO_NOT_OPEN,
        evidence_probes=CLAUDE_CODE_EVIDENCE_PROBES,
        version_detection=VersionDetectionMethod.FILE_MARKER,
    )
