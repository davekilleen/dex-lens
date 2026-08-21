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
    "CLAUDE_CODE_ADAPTER_ID",
    "CLAUDE_CODE_CONTRACT_VERSION",
    "CLAUDE_CODE_DIAGNOSTIC_BASENAMES",
    "CLAUDE_CODE_EVIDENCE_PROBES",
    "GLOBALLY_DENIED_PATHS",
    "claude_code_contract",
]

CLAUDE_CODE_ADAPTER_ID = "claude-code-local"
CLAUDE_CODE_CONTRACT_VERSION = "0.1.0"

#: Probe ids the collector implements; the contract declares exactly these.
CLAUDE_CODE_EVIDENCE_PROBES: tuple[str, ...] = (
    "collection-exclusions",
    "installation-shape",
    "instructions-present",
    "settings-present",
    "skills-present",
)

#: File names every probe in :data:`CLAUDE_CODE_EVIDENCE_PROBES` depends on.
#:
#: This does **not** widen the approved scope — it orders capture inside it.
#: An approved root is often a whole working folder, so the admitted set can
#: be two orders of magnitude larger than the diagnosis needs; on a real
#: 151k-file vault the file-count bound was exhausted before most of these
#: were reached, and the presence probes then reported on an arbitrary
#: fraction of the scope. Capturing declared names first makes the bound bite
#: on material the diagnosis does not use.
CLAUDE_CODE_DIAGNOSTIC_BASENAMES: frozenset[str] = frozenset(
    {
        "CLAUDE.md",
        "SKILL.md",
        "settings.json",
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
