"""R2 evidence-state vocabulary, evidence items, and Evidence Level mapping.

Module M-B slice (HANDOFF.md Section 2.3; gates.md R2). Everything here is
read-only data modeling on the diagnosis side: no module in this package may
expose a mutating entry point (non-negotiable boundary 1).

The R2 state vocabulary and its Evidence Level mapping are the shared
currency of G3, G5, T7, and P1 — changing either re-opens all four.
"""

from capability_exchange.evidence.item import EvidenceItem
from capability_exchange.evidence.levels import (
    NEVER_VERIFIED_STATES,
    EvidenceLevel,
    evidence_level,
)
from capability_exchange.evidence.states import (
    CLAIM_SUPPORTING_STATES,
    EvidenceState,
    coerce_state,
    supports_claims,
)

__all__ = [
    "CLAIM_SUPPORTING_STATES",
    "EvidenceItem",
    "EvidenceLevel",
    "EvidenceState",
    "NEVER_VERIFIED_STATES",
    "coerce_state",
    "evidence_level",
    "supports_claims",
]
