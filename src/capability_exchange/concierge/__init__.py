"""Local browser concierge for the read-only Dex Lens journey (M3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from capability_exchange.concierge.journey import (
    CollectionFallback,
    ConciergeJourney,
    ConciergeStage,
    ContractFields,
    FallbackEvidence,
    FallbackMode,
    InspectionPermission,
    JobDraftFields,
    JourneyError,
    JourneyStateError,
    PermissionMetadata,
    SuccessContractFields,
)

if TYPE_CHECKING:
    from capability_exchange.concierge.server import (
        ConciergeServer,
        ConciergeSession,
        new_session,
    )


def __getattr__(name: str) -> Any:
    """Load server exports lazily so contribution transports can import journey types."""

    if name in {"ConciergeServer", "ConciergeSession", "new_session"}:
        from capability_exchange.concierge import server

        return getattr(server, name)
    raise AttributeError(name)

__all__ = [
    "CollectionFallback",
    "ConciergeJourney",
    "ConciergeServer",
    "ConciergeSession",
    "ConciergeStage",
    "ContractFields",
    "FallbackEvidence",
    "FallbackMode",
    "InspectionPermission",
    "JobDraftFields",
    "JourneyError",
    "JourneyStateError",
    "PermissionMetadata",
    "SuccessContractFields",
    "new_session",
]
