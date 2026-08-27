"""Bounded collection lifecycle used by the local concierge.

This layer keeps the adapter's result private until the approved scope has
been revalidated.  Cancellation is cooperative for in-process collectors and
is also a publication barrier: even a collector that notices cancellation late
cannot publish a partial result into the browser session.
"""

from __future__ import annotations

import hashlib
import inspect
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adapter import AdapterResultEnvelope, InstrumentHealth, ProbeResult
from capability_exchange.adapters.claude_code.containment import (
    GUIDED_FALLBACK_MESSAGE,
    ContainmentUnavailableError,
)
from capability_exchange.diagnosis.provenance import SourceClass, SourceProvenance
from capability_exchange.evidence import EvidenceItem, EvidenceState

__all__ = [
    "CollectionCancelled",
    "CollectionController",
    "CollectionResult",
    "ApprovedSourceDescriptor",
    "ScopeSnapshot",
    "containment_fallback",
]


class CollectionCancelled(RuntimeError):
    """Collection was cancelled; all partials are discarded."""


@dataclass(frozen=True, slots=True)
class ApprovedSourceDescriptor:
    """Consent-bound identity for one canonical approved root.

    The canonical root remains private collection state. Only its opaque
    source id, closed class, and non-reversible scope reference can cross
    into the diagnosis fingerprint.
    """

    canonical_root: Path
    source_id: str
    source_class: SourceClass
    scope_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_root", Path(self.canonical_root))
        validated = SourceProvenance(
            source_id=self.source_id,
            source_class=self.source_class,
            scope_reference=self.scope_reference,
            relative_reference=".",
        )
        object.__setattr__(self, "source_id", validated.source_id)
        object.__setattr__(self, "source_class", validated.source_class)
        object.__setattr__(self, "scope_reference", validated.scope_reference)


@dataclass(frozen=True, slots=True)
class _ScopeIdentity:
    requested: Path
    resolved: Path
    st_dev: int
    st_ino: int
    st_mode: int
    descriptor: ApprovedSourceDescriptor


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    """The canonical roots and identities approved for one collection run."""

    roots: tuple[_ScopeIdentity, ...]

    @classmethod
    def capture(
        cls,
        approved_roots: Iterable[Path],
        *,
        source_descriptors: Iterable[ApprovedSourceDescriptor | Mapping[str, object]] | None = None,
    ) -> ScopeSnapshot:
        raw_roots = tuple(approved_roots)
        if not raw_roots:
            raise ValueError("approved scope is empty")
        if source_descriptors is None:
            if len(raw_roots) != 1:
                raise ValueError(
                    "source descriptors are mandatory when more than one root is approved"
                )
            requested = Path(raw_roots[0])
            try:
                resolved = requested.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError(f"approved scope cannot be snapshotted: {requested}") from exc
            descriptors = (
                ApprovedSourceDescriptor(
                    canonical_root=resolved,
                    source_id="scope:primary",
                    source_class=SourceClass.VAULT_AUTHORED,
                    scope_reference=(
                        "scope:sha256:" + hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
                    ),
                ),
            )
        else:
            descriptors = tuple(
                item
                if isinstance(item, ApprovedSourceDescriptor)
                else ApprovedSourceDescriptor(**item)
                for item in source_descriptors
            )
        descriptor_roots = [item.canonical_root for item in descriptors]
        descriptor_ids = [item.source_id for item in descriptors]
        if len(descriptor_roots) != len(set(descriptor_roots)):
            raise ValueError("source descriptors contain a duplicate canonical root")
        if len(descriptor_ids) != len(set(descriptor_ids)):
            raise ValueError("source descriptors contain a duplicate source_id")

        identities: list[_ScopeIdentity] = []
        seen: set[Path] = set()
        resolved_roots: list[Path] = []
        for raw in raw_roots:
            requested = Path(raw)
            try:
                resolved = requested.resolve(strict=True)
                stat = resolved.stat()
            except (OSError, RuntimeError) as exc:
                raise ValueError(f"approved scope cannot be snapshotted: {requested}") from exc
            if not resolved.is_dir():
                raise ValueError(f"approved scope is not a directory: {requested}")
            if resolved in seen:
                raise ValueError(f"approved scope contains duplicate root: {requested}")
            seen.add(resolved)
            resolved_roots.append(resolved)
            matches = [item for item in descriptors if item.canonical_root == resolved]
            if len(matches) != 1:
                raise ValueError(
                    "source descriptor coverage must match every approved root exactly"
                )
            identities.append(
                _ScopeIdentity(
                    requested=requested,
                    resolved=resolved,
                    st_dev=stat.st_dev,
                    st_ino=stat.st_ino,
                    st_mode=stat.st_mode,
                    descriptor=matches[0],
                )
            )
        if not identities:
            raise ValueError("approved scope is empty")
        if set(descriptor_roots) != set(resolved_roots):
            raise ValueError(
                "source descriptor coverage contains an unknown or missing approved root"
            )
        return cls(tuple(identities))

    @property
    def approved_roots(self) -> tuple[Path, ...]:
        return tuple(identity.resolved for identity in self.roots)

    @property
    def requested_roots(self) -> tuple[Path, ...]:
        return tuple(identity.requested for identity in self.roots)

    @property
    def source_descriptors(self) -> tuple[ApprovedSourceDescriptor, ...]:
        """The immutable descriptor mapping fixed at consent capture."""

        return tuple(identity.descriptor for identity in self.roots)

    def descriptor_for(self, canonical_path: Path) -> ApprovedSourceDescriptor:
        """Return the one approved descriptor containing ``canonical_path``."""

        path = Path(canonical_path).resolve(strict=False)
        matches = [
            identity.descriptor
            for identity in self.roots
            if path == identity.resolved or identity.resolved in path.parents
        ]
        if len(matches) != 1:
            raise ValueError("canonical path belongs to no single approved source")
        return matches[0]

    def revalidate(self, approved_roots: Iterable[Path] | None = None) -> None:
        """Refuse if a root disappeared, was replaced, or the approved set changed."""

        current_raw = tuple(approved_roots) if approved_roots is not None else self.requested_roots
        if len(current_raw) != len(self.roots):
            raise ValueError("approved scope changed before result publication")
        current: list[_ScopeIdentity] = []
        for raw in current_raw:
            requested = Path(raw)
            try:
                resolved = requested.resolve(strict=True)
                stat = resolved.stat()
            except (OSError, RuntimeError) as exc:
                raise ValueError("approved scope changed before result publication") from exc
            current.append(
                _ScopeIdentity(
                    requested=requested,
                    resolved=resolved,
                    st_dev=stat.st_dev,
                    st_ino=stat.st_ino,
                    st_mode=stat.st_mode,
                    descriptor=self.descriptor_for(resolved),
                )
            )
        if tuple(current) != self.roots:
            raise ValueError("approved scope changed before result publication")


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """A result safe to expose after scope and cancellation checks."""

    envelope: AdapterResultEnvelope
    fallback: bool = False
    message: str = ""


class CollectionController:
    """Run one collector with cancellation and a publication barrier."""

    def __init__(
        self,
        approved_roots: Iterable[Path],
        *,
        scope_provider: Callable[[], Iterable[Path]] | None = None,
        scope_snapshot: ScopeSnapshot | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.approved_roots = tuple(Path(root) for root in approved_roots)
        self.scope_provider = scope_provider
        self._consent_snapshot = scope_snapshot
        self.timeout_seconds = timeout_seconds
        self.cancel_event = threading.Event()
        self._lock = threading.RLock()
        self._snapshot: ScopeSnapshot | None = None
        self._result: CollectionResult | None = None
        self._error: BaseException | None = None
        self._collecting = False
        self.cancelled = False

    def collect(
        self,
        collector: Callable[..., AdapterResultEnvelope | CollectionResult],
        *,
        approved_roots: Iterable[Path] | None = None,
    ) -> CollectionResult:
        """Collect once, publishing only after final cancellation/scope checks."""

        with self._lock:
            if self._collecting:
                raise RuntimeError("collection is already in flight")
            if self._result is not None:
                return self._result
            if self.cancelled or self.cancel_event.is_set():
                raise CollectionCancelled("collection cancelled before it started")
            roots = self._current_roots(approved_roots)
            if self._consent_snapshot is not None:
                self._consent_snapshot.revalidate(roots)
                self._snapshot = self._consent_snapshot
            else:
                self._snapshot = ScopeSnapshot.capture(roots)
            snapshot = self._snapshot
            self._collecting = True

        try:
            if self.cancel_event.is_set():
                raise CollectionCancelled("collection cancelled before it started")
            value = self._run_collector(
                collector,
                snapshot=snapshot,
                monitor_live_scope=approved_roots is None,
            )
            if self.cancel_event.is_set() or self.cancelled:
                raise CollectionCancelled("collection cancelled while in flight")
            snapshot.revalidate(roots)
            if isinstance(value, CollectionResult):
                result = value
            else:
                result = CollectionResult(envelope=value)
            with self._lock:
                if self.cancel_event.is_set() or self.cancelled:
                    raise CollectionCancelled("collection cancelled before publication")
                snapshot.revalidate(roots)
                self._result = result
                return result
        except ContainmentUnavailableError as exc:
            # A containment failure is not an HTTP error and must not be
            # represented as a Verified collection.  The fallback envelope is
            # explicit about being blocked and names the guided path.
            result = containment_fallback(str(exc))
            with self._lock:
                if self.cancel_event.is_set() or self.cancelled:
                    raise CollectionCancelled(
                        "collection cancelled before fallback publication"
                    ) from exc
                snapshot.revalidate(roots)
                self._result = result
                return result
        except BaseException as exc:
            with self._lock:
                self._error = exc
            if isinstance(exc, ValueError):
                raise
            if self.cancel_event.is_set() or self.cancelled:
                raise CollectionCancelled("collection cancelled; partial result discarded") from exc
            raise
        finally:
            with self._lock:
                self._collecting = False

    def _invoke_collector(
        self, collector: Callable[..., AdapterResultEnvelope | CollectionResult]
    ) -> AdapterResultEnvelope | CollectionResult:
        """Pass the cancellation event to collectors that opt into it."""

        try:
            signature = inspect.signature(collector)
            positional = tuple(
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
            )
            accepts_event = bool(positional) or any(
                parameter.kind is parameter.VAR_POSITIONAL
                for parameter in signature.parameters.values()
            )
        except (TypeError, ValueError):
            accepts_event = False
        if accepts_event:
            return collector(self.cancel_event)
        return collector()

    def _run_collector(
        self,
        collector: Callable[..., AdapterResultEnvelope | CollectionResult],
        *,
        snapshot: ScopeSnapshot,
        monitor_live_scope: bool,
    ) -> AdapterResultEnvelope | CollectionResult:
        """Run the adapter in a bounded worker so cancellation is responsive."""

        value: list[AdapterResultEnvelope | CollectionResult] = []
        failure: list[BaseException] = []

        def run() -> None:
            try:
                value.append(self._invoke_collector(collector))
            except BaseException as exc:  # hand the error to the owner thread
                failure.append(exc)

        worker = threading.Thread(target=run, name="dex-lens-collection", daemon=True)
        worker.start()
        deadline = time.monotonic() + self.timeout_seconds
        while worker.is_alive():
            worker.join(timeout=0.05)
            if self.cancel_event.is_set():
                self._require_worker_stopped(worker)
                raise CollectionCancelled("collection cancelled while in flight")
            if monitor_live_scope:
                try:
                    snapshot.revalidate(self._current_roots(None))
                except ValueError as exc:
                    self.cancel_event.set()
                    self._require_worker_stopped(worker)
                    raise ValueError(
                        "approved scope changed during collection; reads were stopped"
                    ) from exc
            if time.monotonic() >= deadline:
                self.cancel_event.set()
                self._require_worker_stopped(worker)
                raise CollectionCancelled("collection timed out; partial result discarded")
        if failure:
            raise failure[0]
        if not value:
            raise RuntimeError("collection worker ended without a result")
        return value[0]

    @staticmethod
    def _require_worker_stopped(worker: threading.Thread) -> None:
        """Refuse publication unless cooperative/process cancellation completed."""

        worker.join(timeout=0.5)
        if worker.is_alive():
            raise CollectionCancelled(
                "collection stop could not be proven; session must terminate as an incident"
            )

    def _current_roots(self, approved_roots: Iterable[Path] | None) -> tuple[Path, ...]:
        if approved_roots is not None:
            source = approved_roots
        elif self.scope_provider is not None:
            source = self.scope_provider()
        else:
            source = self.approved_roots
        return tuple(Path(root) for root in source)

    def cancel(self) -> None:
        """Request cancellation and make publication impossible immediately."""

        with self._lock:
            self.cancelled = True
            self.cancel_event.set()
            # Discard a result already held by a caller that has not yet read it.
            self._result = None

    def revalidate_scope(self, approved_roots: Iterable[Path] | None = None) -> None:
        """Revalidate the live approved-root set before a caller publishes UI."""

        with self._lock:
            snapshot = self._snapshot
            roots = self._current_roots(approved_roots)
        if snapshot is None:
            raise ValueError("collection has not started")
        snapshot.revalidate(roots)

    def result(self) -> CollectionResult:
        """Return the published result or the terminal collection error."""

        with self._lock:
            if self._error is not None:
                raise self._error
            if self.cancelled or self.cancel_event.is_set():
                raise CollectionCancelled("collection cancelled; partial result discarded")
            if self._result is not None:
                return self._result
        raise ValueError("collection has not published a result")


def containment_fallback(reason: str, *, now: datetime | None = None) -> CollectionResult:
    """Build an honest guided/export-assisted result with no claim evidence."""

    captured_at = now or datetime.now(UTC)
    bounded_reason = " ".join(str(reason).split())[:400] or "containment unavailable"
    detail = f"containment unavailable: {bounded_reason}"
    envelope = AdapterResultEnvelope(
        adapter_id="claude-code-local",
        contract_version="0.1.0",
        collected_at=captured_at,
        probes=(
            ProbeResult(
                probe_id="containment",
                health=InstrumentHealth.COULD_NOT_CHECK,
                detail=detail,
                evidence=(
                    EvidenceItem(
                        state=EvidenceState.BLOCKED,
                        captured_at=captured_at,
                        reference="containment:unavailable",
                    ),
                ),
            ),
        ),
    )
    return CollectionResult(
        envelope=envelope,
        fallback=True,
        message=f"{GUIDED_FALLBACK_MESSAGE} Reason: {bounded_reason}.",
    )
