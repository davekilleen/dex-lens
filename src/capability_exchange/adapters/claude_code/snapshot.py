"""Immutable inspection snapshot taken at consent time (gates.md G1 item c).

:func:`take_snapshot` reads the approved scope exactly once — through the
canonicalized allowlist, under the collection bounds, with secrets redacted
at collection — into an in-memory snapshot. **All subsequent reads come
from the snapshot, never live disk**: :meth:`InspectionSnapshot.content_of`
serves stored (already-redacted) bytes and refuses paths the snapshot does
not hold; nothing here falls through to the filesystem.

A file that changes mid-inspection is detected by digest mismatch
(:meth:`InspectionSnapshot.changed_paths_since_capture`) so the affected
evidence can be degraded per R2 (``conflicting``). Runtime ambiguity —
resolution races, unreadable metadata during the integrity recheck — raises
:class:`InspectionAbortedError`: the inspection aborts and partials are
discarded, never best-effort live reads (G1 fail-closed rule).

Bounded collection mirrors dex-core's discipline: max file count, max bytes
per file, max total bytes; every bound hit is recorded as an honest R2
exclusion (``blocked``), and a bound that stops collection early marks the
snapshot incomplete — incomplete never extrapolates to complete.

The same rule covers every other way an admitted file goes unread — over the
per-file bound, grown past it mid-read, or impossible to open at all. An
unread file is indistinguishable downstream from a file that is not there:
the presence probes and the inventory both see an absence. So each one marks
the snapshot incomplete and is named in
:attr:`InspectionSnapshot.unread_files` with the reason, because a caveat
that cannot say which file was missed is not actionable.
"""

from __future__ import annotations

import hashlib
import os
import secrets as secrets_module
import stat as stat_module
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING

from capability_exchange.adapters.claude_code.allowlist import (
    CanonicalAllowlist,
    PathDecision,
    PathVerdict,
)
from capability_exchange.adapters.claude_code.contract import CLAUDE_CODE_DIAGNOSTIC_BASENAMES
from capability_exchange.adapters.claude_code.secrets import redact_secret_content
from capability_exchange.evidence import EvidenceItem, EvidenceState
from capability_exchange.evidence.item import reference_rejection_reason

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "CollectionBounds",
    "InspectionAbortedError",
    "InspectionSnapshot",
    "SnapshotEntry",
    "SnapshotError",
    "reference_token",
    "SnapshotMissError",
    "UnreadFile",
    "take_snapshot",
]


class SnapshotError(Exception):
    """Base class for snapshot refusals."""


class InspectionAbortedError(SnapshotError):
    """Runtime ambiguity: the inspection aborts and partials are discarded."""


class SnapshotMissError(SnapshotError):
    """A read was requested for a path the snapshot does not hold.

    The snapshot never falls through to live disk; an un-snapshotted path
    is unreadable, honestly.
    """


@dataclass(frozen=True, slots=True)
class CollectionBounds:
    """Explicit bounds on one collection (dex-core's bounding discipline).

    ``max_total_bytes`` is the guard that matters: it is what actually caps
    the memory one capture can hold. ``max_file_count`` is a runaway guard on
    top of it, and at 2048 it was the binding constraint rather than the
    backstop. A heavily customised personal system is exactly the case Lens
    exists to inspect, and one real vault carries 6,421 files the probes
    declare an interest in — under a third of which fitted. The capture then
    described an arbitrary slice of the approved scope. Those 6,421 files
    total 50.9 MB, inside the byte bound, so the count is raised until bytes
    are once again what binds.
    """

    max_file_count: int = 16384
    max_file_bytes: int = 1 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024

    def as_payload(self) -> dict[str, int]:
        return {
            "max_file_count": self.max_file_count,
            "max_file_bytes": self.max_file_bytes,
            "max_total_bytes": self.max_total_bytes,
        }


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """One captured file: metadata, raw-content digest, redacted content.

    ``content`` holds the **redacted** bytes — raw secret bytes never enter
    the snapshot. ``raw_digest`` is the SHA-256 of the raw bytes as read,
    kept in memory only, for mid-inspection change detection: it is
    **never** placed in any reference, envelope, or other serializable
    structure, because an unkeyed hash of file content is a verifiable
    derivation of that content (G2: derived representations are bounded the
    same as raw ones). ``keyed_digest`` is the reference-safe form: a
    per-inspection-keyed digest of the redacted content, unlinkable to the
    content without the key, which dies with the inspection process.
    """

    canonical_path: str
    relative_path: str
    raw_byte_size: int
    raw_digest: str
    keyed_digest: str
    content: bytes
    redaction_count: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class UnreadFile:
    """One file the allowlist admitted and the capture did not read.

    ``token`` is the reference-safe form that appears in the exclusion
    record. ``relative_path`` is the path as the walk saw it — untrusted
    text from the inspected system, kept beside the token so a reader can
    be told *which* file was missed. It is held in memory only, exactly as
    :attr:`SnapshotEntry.relative_path` is, and never substituted for the
    token in a reference: whoever renders it owes it the same treatment as
    any other inspected text, and must fall back to the token when the name
    cannot be shown honestly.
    """

    reason: str
    relative_path: str
    token: str


#: Bytes that make a raw path unusable as a single-line reference token.
_TOKEN_UNSAFE = frozenset(range(0x00, 0x20)) | {0x7F, ord("\\")}


def reference_token(relative_path: str) -> str:
    """A reference-safe token for a path: short, single-line, low word count.

    A path with control characters, backslashes, excess length, too many
    spaces, **or anything the reference schema itself would reject** is
    replaced by a digest token — a hostile file name must never be able to
    poison a reference and abort the inspection (G1: inspected names are
    untrusted data too).

    The schema's own rule is consulted directly rather than re-stated here.
    When the two were merely similar, a file named ``-----BEGIN`` produced a
    token this function passed through and ``EvidenceItem`` then rejected,
    raising mid-collection: one oddly-named file disabled the deep adapter.
    A producer of references must fail closed on exactly what the consumer
    rejects.
    """
    if (
        len(relative_path) <= 200
        and relative_path.count(" ") <= 3
        and not any(ord(char) in _TOKEN_UNSAFE for char in relative_path)
        and reference_rejection_reason(relative_path) is None
    ):
        return relative_path
    digest = hashlib.sha256(relative_path.encode("utf-8", "surrogateescape")).hexdigest()
    return f"sha256:{digest[:16]}"


def _exclusion_item(reason: str, token: str, *, taken_at: datetime, absent: bool) -> EvidenceItem:
    return EvidenceItem(
        state=EvidenceState.ABSENT if absent else EvidenceState.BLOCKED,
        captured_at=taken_at,
        reference=f"excluded:{reason}:{token}",
    )


def _exclusion_for(decision: PathDecision, taken_at: datetime) -> EvidenceItem:
    token = reference_token(decision.relative_path or os.path.basename(decision.given_path))
    return _exclusion_item(
        decision.reason,
        token,
        taken_at=taken_at,
        absent=decision.verdict is PathVerdict.ABSENT,
    )


def _live_identity(canonical_path: str, byte_bound: int) -> tuple[str, int] | None:
    """(SHA-256, mtime_ns) of a live file for the integrity recheck.

    Returns ``None`` if the file is gone. Both the content digest and the
    modification time are compared: digest equality alone has an ABA blind
    spot — a file mutated and mutated back (or recheck-read at a moment its
    bytes coincide with the capture, e.g. mid-truncate) would pass as
    unchanged. Content read here feeds the comparison only — it never
    becomes evidence. Ambiguity (non-ENOENT errors, symlink reappearing)
    raises :class:`InspectionAbortedError`.
    """
    try:
        fd = os.open(canonical_path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InspectionAbortedError(
            f"integrity recheck could not access a snapshotted path "
            f"({type(exc).__name__}); runtime ambiguity aborts the inspection "
            f"and discards partials"
        ) from exc
    try:
        metadata = os.fstat(fd)
        hasher = hashlib.sha256()
        consumed = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > byte_bound:
                # Larger than anything the snapshot could hold: changed.
                return ("oversized", metadata.st_mtime_ns)
            hasher.update(chunk)
        return (hasher.hexdigest(), metadata.st_mtime_ns)
    except OSError as exc:
        raise InspectionAbortedError(
            f"integrity recheck failed mid-read ({type(exc).__name__}); "
            f"runtime ambiguity aborts the inspection and discards partials"
        ) from exc
    finally:
        os.close(fd)


class InspectionSnapshot:
    """The immutable in-memory capture all inspection reads come from."""

    def __init__(
        self,
        *,
        taken_at: datetime,
        entries: dict[str, SnapshotEntry],
        exclusions: tuple[EvidenceItem, ...],
        bounds: CollectionBounds,
        complete: bool,
        unread_files: tuple[UnreadFile, ...] = (),
    ) -> None:
        self._taken_at = taken_at
        self._entries: Mapping[str, SnapshotEntry] = MappingProxyType(dict(entries))
        self._exclusions = exclusions
        self._bounds = bounds
        self._complete = complete
        self._unread_files = unread_files

    @property
    def taken_at(self) -> datetime:
        return self._taken_at

    @property
    def bounds(self) -> CollectionBounds:
        return self._bounds

    @property
    def complete(self) -> bool:
        """False when any admitted file went unread. Never extrapolated.

        A bound that stopped collection early, a file too large to read, and
        a file that could not be opened all land here: each one leaves the
        snapshot describing less than the approved scope.
        """
        return self._complete

    @property
    def unread_files(self) -> tuple[UnreadFile, ...]:
        """Every admitted file the capture did not read, and why.

        Non-empty exactly when :attr:`complete` is False, so a caveat built
        from it can name the files instead of only announcing that some
        exist.
        """
        return self._unread_files

    @property
    def exclusions(self) -> tuple[EvidenceItem, ...]:
        """Honest R2 exclusion records (``blocked`` / ``absent``)."""
        return self._exclusions

    def canonical_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def entry_for(self, canonical_path: str) -> SnapshotEntry:
        entry = self._entries.get(canonical_path)
        if entry is None:
            raise SnapshotMissError(
                "path is not in the inspection snapshot; snapshot reads never "
                "fall through to live disk"
            )
        return entry

    def content_of(self, canonical_path: str) -> bytes:
        """The stored (redacted) content. Never a live-disk read."""
        return self.entry_for(canonical_path).content

    def entries_named(self, basename: str) -> tuple[SnapshotEntry, ...]:
        """All entries whose file name equals ``basename`` (sorted)."""
        return tuple(
            self._entries[path]
            for path in sorted(self._entries)
            if os.path.basename(path) == basename
        )

    def changed_paths_since_capture(self) -> frozenset[str]:
        """Canonical paths whose live identity no longer matches the snapshot.

        Compares content digest **and** mtime — a mutation whose recheck
        bytes coincide with the capture (ABA) is still a change. Deletion
        counts as change. Any ambiguity raises
        :class:`InspectionAbortedError` (fail closed).
        """
        changed: set[str] = set()
        for canonical_path, entry in self._entries.items():
            live = _live_identity(canonical_path, self._bounds.max_file_bytes)
            if live != (entry.raw_digest, entry.mtime_ns):
                changed.add(canonical_path)
        return frozenset(changed)


def _diagnostic_files_first(admitted: Sequence[PathDecision]) -> list[PathDecision]:
    """Order admitted files so the diagnosis is captured before the bound bites.

    This changes **capture order only**. Nothing is admitted that the
    allowlist did not already admit, nothing is skipped that the bounds
    would not already have skipped, and the bounds themselves are unchanged.

    Without it the file-count bound is spent on whatever the walk reached
    first. An approved root is usually a whole working folder, so on a real
    151k-file vault the 2048-file bound was exhausted long before most
    ``SKILL.md`` files were reached, and the presence probes then described
    an arbitrary 1.4% of the approved scope. Ordering by declared relevance
    means the bound now bites on material no probe reads.

    The sort is stable, so files sharing a priority keep the allowlist's own
    deterministic order and two runs over an unchanged tree still agree.
    """
    return sorted(
        admitted,
        key=lambda decision: (
            0
            if os.path.basename(decision.relative_path or "") in CLAUDE_CODE_DIAGNOSTIC_BASENAMES
            else 1
        ),
    )


def take_snapshot(
    allowlist: CanonicalAllowlist,
    *,
    bounds: CollectionBounds | None = None,
    taken_at: datetime | None = None,
) -> InspectionSnapshot:
    """Capture the approved scope once, at consent time.

    Reads happen only through admitted allowlist decisions (canonical real
    paths), secrets are redacted before content enters the snapshot, and
    every refusal or bound hit becomes an honest exclusion record. An
    ambiguous decision aborts the whole capture and discards partials.
    """
    effective_bounds = bounds or CollectionBounds()
    moment = taken_at or datetime.now(UTC)
    # Per-inspection reference key: keyed digests in references are
    # unlinkable to file content without this key, which never leaves the
    # inspection process (an unkeyed content hash would be a verifiable
    # derivation of the content — G2 counts derivations as data).
    reference_key = secrets_module.token_bytes(16)
    outcome = allowlist.survey()

    exclusions: list[EvidenceItem] = []
    for decision in outcome.excluded:
        if decision.ambiguous:
            raise InspectionAbortedError(
                f"path resolution was ambiguous ({decision.reason}); the "
                f"inspection aborts and partial collection is discarded"
            )
        exclusions.append(_exclusion_for(decision, moment))

    entries: dict[str, SnapshotEntry] = {}
    unread: list[UnreadFile] = []
    total_bytes = 0
    complete = True

    def not_read(reason: str, token: str, relative_path: str) -> None:
        """Record an admitted file this capture did not read.

        Every route out of the loop below that produces no entry goes
        through here, because they are the same event to everyone
        downstream: the file is simply not in the snapshot, and a reader
        cannot tell "too big to read" or "could not be opened" from "not
        there". Two of these routes used to leave ``complete`` True, so a
        folder whose only ``CLAUDE.md`` was a byte over the per-file bound
        rendered as an uncaveated empty list — which reads as "you have no
        instruction file", the one claim a bounded capture may never make.
        """
        nonlocal complete
        exclusions.append(_exclusion_item(reason, token, taken_at=moment, absent=False))
        unread.append(UnreadFile(reason=reason, relative_path=relative_path, token=token))
        complete = False

    for decision in _diagnostic_files_first(outcome.admitted_files):
        canonical_path = decision.canonical_path
        relative_path = decision.relative_path
        assert canonical_path is not None and relative_path is not None
        if canonical_path in entries:
            continue  # an in-scope symlink and its target: capture once
        token = reference_token(relative_path)
        if len(entries) >= effective_bounds.max_file_count:
            not_read("file-count-bound-reached", token, relative_path)
            continue
        try:
            fd = os.open(
                canonical_path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            )
        except OSError:
            not_read("read-error", token, relative_path)
            continue
        try:
            metadata = os.fstat(fd)
            if not stat_module.S_ISREG(metadata.st_mode) or metadata.st_nlink > 1:
                not_read("changed-between-approval-and-read", token, relative_path)
                continue
            if metadata.st_size > effective_bounds.max_file_bytes:
                not_read("read-bound-exceeded", token, relative_path)
                continue
            if total_bytes + metadata.st_size > effective_bounds.max_total_bytes:
                not_read("total-bytes-bound-reached", token, relative_path)
                continue
            chunks: list[bytes] = []
            consumed = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                consumed += len(chunk)
                if consumed > effective_bounds.max_file_bytes:
                    break
                chunks.append(chunk)
            if consumed > effective_bounds.max_file_bytes:
                # A file that grew past the bound mid-read is excluded
                # rather than partially captured.
                not_read("read-bound-exceeded", token, relative_path)
                continue
            raw = b"".join(chunks)
        except OSError:
            not_read("read-error", token, relative_path)
            continue
        finally:
            os.close(fd)

        redaction = redact_secret_content(raw)
        entries[canonical_path] = SnapshotEntry(
            canonical_path=canonical_path,
            relative_path=relative_path,
            raw_byte_size=len(raw),
            raw_digest=hashlib.sha256(raw).hexdigest(),
            keyed_digest=hashlib.blake2b(
                redaction.content, key=reference_key, digest_size=8
            ).hexdigest(),
            content=redaction.content,
            redaction_count=redaction.redaction_count,
            mtime_ns=metadata.st_mtime_ns,
        )
        total_bytes += len(raw)
        del raw  # raw bytes (possibly secret-bearing) do not outlive this loop

    return InspectionSnapshot(
        taken_at=moment,
        entries=entries,
        exclusions=tuple(exclusions),
        bounds=effective_bounds,
        complete=complete,
        unread_files=tuple(unread),
    )
