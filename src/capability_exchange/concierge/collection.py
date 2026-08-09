"""Bounded collection lifecycle used by the local concierge.

This layer keeps the adapter's result private until the approved scope has
been revalidated.  Cancellation is cooperative for in-process collectors and
is also a publication barrier: even a collector that notices cancellation late
cannot publish a partial result into the browser session.
"""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adapter import AdapterResultEnvelope, InstrumentHealth, ProbeResult
from capability_exchange.adapters.claude_code.containment import (
    GUIDED_FALLBACK_MESSAGE,
    ContainmentUnavailableError,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

__all__ = [
    "CollectionCancelled",
    "CollectionController",
    "CollectionResult",
    "ScopeSnapshot",
    "containment_fallback",
]


class CollectionCancelled(RuntimeError):
    """Collection was cancelled; all partials are discarded."""


@dataclass(frozen=True, slots=True)
class _ScopeIdentity:
    requested: Path
    resolved: Path
    st_dev: int
    st_ino: int
    st_mode: int


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    """The canonical roots and identities approved for one collection run."""

    roots: tuple[_ScopeIdentity, ...]

    @classmethod
    def capture(cls, approved_roots: Iterable[Path]) -> ScopeSnapshot:
        identities: list[_ScopeIdentity] = []
        seen: set[Path] = set()
        for raw in approved_roots:
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
            identities.append(
                _ScopeIdentity(
                    requested=requested,
                    resolved=resolved,
                    st_dev=stat.st_dev,
                    st_ino=stat.st_ino,
                    st_mode=stat.st_mode,
                )
            )
        if not identities:
            raise ValueError("approved scope is empty")
        return cls(tuple(identities))

    @property
    def approved_roots(self) -> tuple[Path, ...]:
        return tuple(identity.resolved for identity in self.roots)

    def revalidate(self, approved_roots: Iterable[Path] | None = None) -> None:
        """Refuse if a root disappeared, was replaced, or the approved set changed."""

        current_raw = tuple(approved_roots) if approved_roots is not None else self.approved_roots
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

    def __init__(self, approved_roots: Iterable[Path], *, timeout_seconds: float = 30.0) -> None:
        self.approved_roots = tuple(Path(root) for root in approved_roots)
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
            roots = tuple(Path(root) for root in (approved_roots or self.approved_roots))
            self._snapshot = ScopeSnapshot.capture(roots)
            snapshot = self._snapshot
            self._collecting = True

        try:
            if self.cancel_event.is_set():
                raise CollectionCancelled("collection cancelled before it started")
            value = self._run_collector(collector)
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
            if self.cancel_event.is_set() or self.cancelled:
                raise CollectionCancelled(
                    "collection cancelled; partial result discarded"
                ) from exc
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
                if parameter.kind
                in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
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
        self, collector: Callable[..., AdapterResultEnvelope | CollectionResult]
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
                worker.join(timeout=0.5)
                raise CollectionCancelled("collection cancelled while in flight")
            if time.monotonic() >= deadline:
                self.cancel_event.set()
                worker.join(timeout=0.5)
                raise CollectionCancelled("collection timed out; partial result discarded")
        if failure:
            raise failure[0]
        if not value:
            raise RuntimeError("collection worker ended without a result")
        return value[0]

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
            roots = tuple(Path(root) for root in (approved_roots or self.approved_roots))
        if snapshot is None:
            raise ValueError("collection has not started")
        snapshot.revalidate(roots)

    def result(self) -> CollectionResult:
        """Return the published result or the terminal collection error."""

        with self._lock:
            if self.cancelled or self.cancel_event.is_set():
                raise CollectionCancelled("collection cancelled; partial result discarded")
            if self._result is not None:
                return self._result
            if self._error is not None:
                raise self._error
        raise ValueError("collection has not published a result")


def containment_fallback(
    reason: str, *, now: datetime | None = None
) -> CollectionResult:
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
