"""The individual conformance checks (HANDOFF 5.4; gates.md G1, R2).

Each check returns a :class:`CheckResult` naming the gate it enforces.
A check that cannot evaluate its subject fails closed: unprovable is
non-conformant, never assumed conformant.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from capability_exchange.adapter import (
    AdapterContract,
    AdapterMode,
    AdapterResultEnvelope,
    ArchivePolicy,
    SymlinkPolicy,
    VersionDetectionMethod,
)
from capability_exchange.evidence import supports_claims

if TYPE_CHECKING:
    from collections.abc import Sequence

    from capability_exchange.conformance.subject import AdapterConformanceSubject

__all__ = [
    "CheckOutcome",
    "CheckResult",
    "check_contract_declaration_completeness",
    "check_honest_fallback",
    "check_result_envelope_conformance",
    "check_snapshot_semantics",
    "tree_identity",
]

#: Tolerated clock skew when judging "captured in the past".
_CLOCK_SKEW = timedelta(seconds=30)


class CheckOutcome(StrEnum):
    """Closed outcome vocabulary for one conformance check."""

    PASSED = "passed"
    FAILED = "failed"
    #: The adapter refused the whole inspection honestly (containment
    #: unavailable, G1 fail-closed) — the check could not run, and that is
    #: conformant behavior only because the refusal itself was verified.
    REFUSED_HONESTLY = "refused-honestly"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One check's verdict, with the gate it enforces and an honest detail."""

    check_id: str
    gate: str
    outcome: CheckOutcome
    detail: str

    @property
    def passed(self) -> bool:
        return self.outcome is CheckOutcome.PASSED


def _passed(check_id: str, gate: str, detail: str) -> CheckResult:
    return CheckResult(check_id=check_id, gate=gate, outcome=CheckOutcome.PASSED, detail=detail)


def _failed(check_id: str, gate: str, detail: str) -> CheckResult:
    return CheckResult(check_id=check_id, gate=gate, outcome=CheckOutcome.FAILED, detail=detail)


# ---------------------------------------------------------------------------
# Tree identity (the zero-writes witness)
# ---------------------------------------------------------------------------


def _xattr_identity(path: Path) -> tuple[tuple[str, str], ...]:
    """Extended attributes as (name, sha256-of-value) pairs, sorted.

    Included in the witness because an xattr write changes no content, size,
    mode, or mtime: a content-and-stat-only witness would call the tree
    byte-identical while the person's system had in fact been modified.
    Filesystems and platforms without xattr support yield an empty tuple —
    the same on both sides of the comparison, so nothing is masked.
    """
    listxattr = getattr(os, "listxattr", None)
    getxattr = getattr(os, "getxattr", None)
    if listxattr is None or getxattr is None:
        return ()
    try:
        names = sorted(listxattr(path, follow_symlinks=False))
    except OSError:
        return ()
    attributes: list[tuple[str, str]] = []
    for name in names:
        try:
            value = getxattr(path, name, follow_symlinks=False)
        except OSError:
            attributes.append((name, "unreadable"))
            continue
        attributes.append((name, hashlib.sha256(value).hexdigest()))
    return tuple(attributes)


def tree_identity(root: Path) -> dict[str, tuple[object, ...]]:
    """A full recursive identity of ``root``: any write anywhere changes it.

    Covers file content (SHA-256), size, mode, mtime_ns, extended
    attributes, directory entry sets and modes, and symlink targets. Never
    follows symlinks — reading through an escape link to build a witness
    would itself be an escape.
    """
    identity: dict[str, tuple[object, ...]] = {}
    root_str = str(root)
    identity[root_str] = (
        "dir",
        root.stat().st_mode,
        tuple(sorted(os.listdir(root))),
        _xattr_identity(root),
    )
    for current_dir, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames):
            full = Path(current_dir) / name
            if full.is_symlink():
                identity[str(full)] = ("symlink", os.readlink(full))
                continue
            metadata = full.stat()
            identity[str(full)] = (
                "dir",
                metadata.st_mode,
                tuple(sorted(os.listdir(full))),
                _xattr_identity(full),
            )
        for name in sorted(filenames):
            full = Path(current_dir) / name
            if full.is_symlink():
                identity[str(full)] = ("symlink", os.readlink(full))
                continue
            metadata = full.lstat()
            identity[str(full)] = (
                "file",
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                hashlib.sha256(full.read_bytes()).hexdigest(),
                _xattr_identity(full),
            )
    return identity


# ---------------------------------------------------------------------------
# Contract-declaration completeness (G1)
# ---------------------------------------------------------------------------


def check_contract_declaration_completeness(
    subject: AdapterConformanceSubject, roots: Sequence[str]
) -> CheckResult:
    """The contract declares everything HANDOFF M-A requires, coherently."""
    check_id, gate = "contract-declaration-completeness", "G1"
    try:
        contract = subject.build_contract(roots)
    except Exception as exc:  # noqa: BLE001 - unprovable => non-conformant
        return _failed(
            check_id, gate, f"contract could not be built ({type(exc).__name__}: {exc})"
        )
    problems: list[str] = []
    if not isinstance(contract, AdapterContract):
        return _failed(check_id, gate, "subject did not produce an AdapterContract")
    if contract.adapter_id != subject.adapter_id:
        problems.append(
            f"contract names adapter {contract.adapter_id!r}, subject drives "
            f"{subject.adapter_id!r}"
        )
    if not contract.discoverable_roots:
        problems.append("no discoverable roots declared")
    if not contract.read_scope:
        problems.append("no explicit read scope declared")
    if not contract.evidence_probes:
        problems.append("no evidence probes declared")
    if not isinstance(contract.symlink_policy, SymlinkPolicy):
        problems.append("symlink policy is not a member of the closed vocabulary")
    if not isinstance(contract.archive_policy, ArchivePolicy):
        problems.append("archive policy is not a member of the closed vocabulary")
    if not isinstance(contract.version_detection, VersionDetectionMethod):
        problems.append("version detection is not a member of the closed vocabulary")
    if contract.mode is not AdapterMode.DIAGNOSE_ONLY and contract.mutation_contract is None:
        problems.append(
            "Adapt-capable declared with no host-specific mutation contract "
            "(#348: no ownership and rewind contract means Diagnose-only)"
        )
    try:
        AdapterContract.model_validate(contract.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"contract does not survive its own round-trip ({type(exc).__name__})")
    if problems:
        return _failed(check_id, gate, "; ".join(problems))
    return _passed(
        check_id,
        gate,
        f"contract {contract.contract_version} declares roots, scope, "
        f"{len(contract.denied_paths)} denied path(s), symlink/archive policy, "
        f"{len(contract.evidence_probes)} probe(s), version detection, and mode "
        f"{contract.mode.value}",
    )


# ---------------------------------------------------------------------------
# Result-envelope conformance (R2)
# ---------------------------------------------------------------------------


def check_result_envelope_conformance(
    contract: AdapterContract, envelope: AdapterResultEnvelope
) -> CheckResult:
    """R2 states, source age, non-raw references; failure never success."""
    check_id, gate = "result-envelope-conformance", "R2"
    problems: list[str] = []
    if envelope.adapter_id != contract.adapter_id:
        problems.append(
            f"envelope names adapter {envelope.adapter_id!r}, contract declares "
            f"{contract.adapter_id!r}"
        )
    if envelope.contract_version != contract.contract_version:
        problems.append("envelope and contract disagree on the contract version")
    declared = set(contract.evidence_probes)
    produced = {probe.probe_id for probe in envelope.probes}
    if produced != declared:
        problems.append(
            f"probes produced {sorted(produced)} != probes declared {sorted(declared)}"
        )
    horizon = datetime.now(UTC) + _CLOCK_SKEW
    if envelope.collected_at > horizon:
        problems.append("collection timestamp claims the future")
    for probe in envelope.probes:
        if not probe.succeeded and not probe.detail.strip():
            problems.append(f"probe {probe.probe_id}: failure without a reported reason")
        if not probe.succeeded:
            for item in probe.evidence:
                if supports_claims(item.state):
                    problems.append(
                        f"probe {probe.probe_id}: failed instrument carries "
                        f"claim-supporting evidence ({item.state.value})"
                    )
        for item in probe.evidence:
            if item.captured_at > horizon:
                problems.append(
                    f"probe {probe.probe_id}: evidence claims a future source age"
                )
            if not item.reference.strip():
                problems.append(f"probe {probe.probe_id}: empty evidence reference")
    try:
        # Round-trip re-validation runs every schema rule, including the
        # non-raw-reference rejection, against the serialized form.
        AdapterResultEnvelope.model_validate(envelope.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"envelope does not survive re-validation ({type(exc).__name__})")
    if problems:
        return _failed(check_id, gate, "; ".join(problems))
    counts = envelope.health_counts()
    return _passed(
        check_id,
        gate,
        f"{len(envelope.probes)} probe(s) conformant "
        f"({', '.join(f'{h.value}={n}' for h, n in counts.items() if n)})",
    )


# ---------------------------------------------------------------------------
# Snapshot semantics (G1 item c)
# ---------------------------------------------------------------------------


def check_snapshot_semantics(
    subject: AdapterConformanceSubject, workspace: Path
) -> CheckResult:
    """Reads come from the consent-time capture, never live disk.

    Runs against a scratch tree the suite builds in its own workspace — the
    person's system is never mutated to prove this.
    """
    check_id, gate = "snapshot-semantics", "G1"
    scratch = workspace / "snapshot-semantics"
    scratch.mkdir(parents=True, exist_ok=True)
    original = b"consent-time bytes\n"
    target = scratch / "capture-me.md"
    target.write_bytes(original)
    (scratch / "second.md").write_bytes(b"second file\n")
    try:
        snapshot = subject.capture_snapshot([str(scratch)])
    except Exception as exc:  # noqa: BLE001
        return _failed(check_id, gate, f"snapshot capture failed ({type(exc).__name__}: {exc})")
    captured = [
        path for path in snapshot.canonical_paths() if path.endswith("capture-me.md")
    ]
    if not captured:
        return _failed(check_id, gate, "consented file missing from the snapshot")
    target_path = captured[0]

    target.write_bytes(b"LIVE MUTATION AFTER CONSENT\n")
    if snapshot.content_of(target_path) != original:
        return _failed(
            check_id,
            gate,
            "a live mutation reached a snapshot read — reads are not being "
            "served from the consent-time capture",
        )
    target.unlink()
    if snapshot.content_of(target_path) != original:
        return _failed(
            check_id, gate, "a deleted file's snapshot read no longer serves capture bytes"
        )
    uncaptured = str(scratch / "never-captured.md")
    try:
        snapshot.content_of(uncaptured)
    except subject.snapshot_miss_error:
        pass
    except Exception as exc:  # noqa: BLE001
        return _failed(
            check_id,
            gate,
            f"un-captured path raised {type(exc).__name__}, not the declared "
            f"snapshot-miss refusal",
        )
    else:
        return _failed(
            check_id,
            gate,
            "un-captured path was readable — the snapshot falls through to live disk",
        )
    return _passed(
        check_id,
        gate,
        "snapshot serves consent-time bytes through live mutation and deletion; "
        "un-captured paths are refused",
    )


# ---------------------------------------------------------------------------
# Honest fallback (G1 fail-closed)
# ---------------------------------------------------------------------------


def check_honest_fallback(
    subject: AdapterConformanceSubject, roots: Sequence[str], system_root: Path
) -> CheckResult:
    """Containment unavailable ⇒ typed refusal, guidance, zero reads/writes."""
    check_id, gate = "honest-fallback", "G1"
    before = tree_identity(system_root)
    try:
        subject.force_containment_unavailable(roots)
    except subject.refusal_error as refusal:
        guidance = getattr(refusal, "fallback_guidance", "")
        if not isinstance(guidance, str) or not guidance.strip():
            return _failed(
                check_id,
                gate,
                "refusal carries no fallback guidance — a disabled deep adapter "
                "must state the guided/export-assisted path honestly",
            )
        if not str(refusal).strip():
            return _failed(check_id, gate, "refusal message is empty")
        if tree_identity(system_root) != before:
            return _failed(check_id, gate, "the refusal path modified the inspected tree")
        return _passed(
            check_id,
            gate,
            "containment-unavailable refuses with typed error and fallback "
            "guidance; inspected tree untouched",
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(
            check_id,
            gate,
            f"containment-unavailable raised {type(exc).__name__}, not the "
            f"declared refusal type",
        )
    return _failed(
        check_id,
        gate,
        "containment-unavailable did NOT refuse — an uncontainable inspection "
        "must never proceed (G1 fail-closed)",
    )
