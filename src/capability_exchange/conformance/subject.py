"""The driving surface a Host Adapter exposes to the conformance suite.

The suite holds an adapter to its **declared contract** — it needs only a
thin, adapter-supplied way to build that contract, run one full inspection,
capture a snapshot, and demonstrate the honest-refusal path. Nothing here
grants the suite (or the adapter) any write capability over the inspected
system; the zero-writes check exists to prove that stays true.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from capability_exchange.adapter import AdapterContract, AdapterResultEnvelope


@runtime_checkable
class SnapshotLike(Protocol):
    """What the suite needs from an adapter's consent-time snapshot."""

    def canonical_paths(self) -> tuple[str, ...]:
        """Every captured canonical path, sorted."""
        ...

    def content_of(self, canonical_path: str) -> bytes:
        """Captured (already-redacted) bytes; raises for un-captured paths."""
        ...


@dataclass(frozen=True, slots=True)
class AdapterConformanceSubject:
    """One adapter, as the conformance suite drives it.

    All callables receive the approved roots as strings. ``inspect`` runs
    one entire inspection (under the adapter's real containment where the
    host provides it) and returns the result envelope, or raises
    ``refusal_error`` when containment cannot be established — that refusal
    must carry a non-empty ``fallback_guidance`` attribute (G1 fail-closed:
    disabled deep adapter, honest guided/export-assisted fallback).
    ``force_containment_unavailable`` exercises exactly that refusal path
    on demand so the suite can verify it without depending on the host
    being broken.
    """

    adapter_id: str
    build_contract: Callable[[Sequence[str]], AdapterContract]
    inspect: Callable[[Sequence[str]], AdapterResultEnvelope]
    capture_snapshot: Callable[[Sequence[str]], SnapshotLike]
    snapshot_miss_error: type[Exception]
    force_containment_unavailable: Callable[[Sequence[str]], AdapterResultEnvelope]
    refusal_error: type[Exception]
