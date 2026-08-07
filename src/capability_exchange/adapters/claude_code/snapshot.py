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
"""

from __future__ import annotations

import hashlib
import os
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
from capability_exchange.adapters.claude_code.secrets import redact_secret_content
from capability_exchange.evidence import EvidenceItem, EvidenceState

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CollectionBounds",
    "InspectionAbortedError",
    "InspectionSnapshot",
    "SnapshotEntry",
    "SnapshotError",
    "reference_token",
    "SnapshotMissError",
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
    """Explicit bounds on one collection (dex-core's bounding discipline)."""

    max_file_count: int = 2048
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
    kept in memory only, for mid-inspection change detection.
    """

    canonical_path: str
    relative_path: str
    raw_byte_size: int
    raw_digest: str
    content: bytes
    redaction_count: int
    mtime_ns: int


def reference_token(relative_path: str) -> str:
    """A reference-safe token for a path: short, single-line, low word count."""
    if len(relative_path) <= 200 and relative_path.count(" ") <= 3:
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


def _digest_of_live_file(canonical_path: str, byte_bound: int) -> str | None:
    """SHA-256 of a live file for the integrity recheck, or None if gone.

    Content read here feeds a digest comparison only — it never becomes
    evidence. Ambiguity (non-ENOENT errors, symlink reappearing) raises
    :class:`InspectionAbortedError`.
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
        hasher = hashlib.sha256()
        consumed = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > byte_bound:
                # Larger than anything the snapshot could hold: changed.
                return "oversized"
            hasher.update(chunk)
        return hasher.hexdigest()
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
    ) -> None:
        self._taken_at = taken_at
        self._entries: Mapping[str, SnapshotEntry] = MappingProxyType(dict(entries))
        self._exclusions = exclusions
        self._bounds = bounds
        self._complete = complete

    @property
    def taken_at(self) -> datetime:
        return self._taken_at

    @property
    def bounds(self) -> CollectionBounds:
        return self._bounds

    @property
    def complete(self) -> bool:
        """False when a bound stopped collection early. Never extrapolated."""
        return self._complete

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
        """Canonical paths whose live bytes no longer match the snapshot.

        Digest comparison only; deletion counts as change. Any ambiguity
        raises :class:`InspectionAbortedError` (fail closed).
        """
        changed: set[str] = set()
        for canonical_path, entry in self._entries.items():
            live = _digest_of_live_file(canonical_path, self._bounds.max_file_bytes)
            if live != entry.raw_digest:
                changed.add(canonical_path)
        return frozenset(changed)


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
    total_bytes = 0
    complete = True

    for decision in outcome.admitted_files:
        canonical_path = decision.canonical_path
        relative_path = decision.relative_path
        assert canonical_path is not None and relative_path is not None
        if canonical_path in entries:
            continue  # an in-scope symlink and its target: capture once
        token = reference_token(relative_path)
        if len(entries) >= effective_bounds.max_file_count:
            exclusions.append(
                _exclusion_item("file-count-bound-reached", token, taken_at=moment, absent=False)
            )
            complete = False
            continue
        try:
            fd = os.open(
                canonical_path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            )
        except OSError:
            exclusions.append(_exclusion_item("read-error", token, taken_at=moment, absent=False))
            continue
        try:
            metadata = os.fstat(fd)
            if not stat_module.S_ISREG(metadata.st_mode) or metadata.st_nlink > 1:
                exclusions.append(
                    _exclusion_item(
                        "changed-between-approval-and-read", token, taken_at=moment, absent=False
                    )
                )
                continue
            if metadata.st_size > effective_bounds.max_file_bytes:
                exclusions.append(
                    _exclusion_item("read-bound-exceeded", token, taken_at=moment, absent=False)
                )
                continue
            if total_bytes + metadata.st_size > effective_bounds.max_total_bytes:
                exclusions.append(
                    _exclusion_item(
                        "total-bytes-bound-reached", token, taken_at=moment, absent=False
                    )
                )
                complete = False
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
                exclusions.append(
                    _exclusion_item("read-bound-exceeded", token, taken_at=moment, absent=False)
                )
                continue
            raw = b"".join(chunks)
        except OSError:
            exclusions.append(_exclusion_item("read-error", token, taken_at=moment, absent=False))
            continue
        finally:
            os.close(fd)

        redaction = redact_secret_content(raw)
        entries[canonical_path] = SnapshotEntry(
            canonical_path=canonical_path,
            relative_path=relative_path,
            raw_byte_size=len(raw),
            raw_digest=hashlib.sha256(raw).hexdigest(),
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
    )
