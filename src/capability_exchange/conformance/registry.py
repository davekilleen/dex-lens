"""Registered conformance subjects, by adapter id.

Every shipped Host Adapter registers how the suite drives it. There is
exactly one deep adapter in M1: local folder-based Claude Code.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.containment import (
    ContainmentUnavailableError,
    LinuxStrategy,
    MacOSStrategy,
    contained_inspection,
)
from capability_exchange.adapters.claude_code.contract import (
    CLAUDE_CODE_ADAPTER_ID,
    claude_code_contract,
)
from capability_exchange.adapters.claude_code.snapshot import (
    SnapshotMissError,
    take_snapshot,
)
from capability_exchange.conformance.subject import AdapterConformanceSubject

if TYPE_CHECKING:
    from collections.abc import Sequence

    from capability_exchange.adapter import AdapterResultEnvelope
    from capability_exchange.adapters.claude_code.snapshot import InspectionSnapshot

__all__ = [
    "UnknownAdapterError",
    "claude_code_conformance_subject",
    "conformance_subject_for",
    "registered_adapter_ids",
]


class UnknownAdapterError(LookupError):
    """No conformance subject is registered for the requested adapter id."""


def _inspect(roots: Sequence[str]) -> AdapterResultEnvelope:
    """One entire inspection under the host's real OS-enforced containment."""
    return contained_inspection(list(roots)).envelope


def _capture_snapshot(roots: Sequence[str]) -> InspectionSnapshot:
    contract = claude_code_contract(list(roots))
    allowlist = CanonicalAllowlist(contract.read_scope, denied_paths=contract.denied_paths)
    return take_snapshot(allowlist)


def _foreign_platform_strategy() -> LinuxStrategy | MacOSStrategy:
    """The other platform's strategy — genuinely unavailable on this host."""
    return LinuxStrategy() if sys.platform == "darwin" else MacOSStrategy()


def _force_containment_unavailable(roots: Sequence[str]) -> AdapterResultEnvelope:
    """Exercise the adapter's real refusal path: an OS-enforced strategy
    that cannot be established on this host must refuse before any read."""
    return contained_inspection(list(roots), strategy=_foreign_platform_strategy()).envelope


def claude_code_conformance_subject() -> AdapterConformanceSubject:
    return AdapterConformanceSubject(
        adapter_id=CLAUDE_CODE_ADAPTER_ID,
        build_contract=lambda roots: claude_code_contract(list(roots)),
        inspect=_inspect,
        capture_snapshot=_capture_snapshot,
        snapshot_miss_error=SnapshotMissError,
        force_containment_unavailable=_force_containment_unavailable,
        refusal_error=ContainmentUnavailableError,
    )


_REGISTRY = {CLAUDE_CODE_ADAPTER_ID: claude_code_conformance_subject}


def registered_adapter_ids() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def conformance_subject_for(adapter_id: str) -> AdapterConformanceSubject:
    factory = _REGISTRY.get(adapter_id)
    if factory is None:
        raise UnknownAdapterError(
            f"no conformance subject registered for {adapter_id!r}; "
            f"registered: {sorted(_REGISTRY)}"
        )
    return factory()
