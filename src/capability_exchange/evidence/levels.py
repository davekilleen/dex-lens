"""Evidence Level and the total R2 state-combination → Level mapping.

HANDOFF.md M-B (normative): the R2 evidence states and the displayed
Evidence Level (Verified / Supported / Reported / Unknown) are distinct
vocabularies; this module ships the machine-readable, TOTAL mapping from R2
state combinations to exactly one Evidence Level.

Normative rules encoded here (property-tested in tests/evidence):

- ``stale``, ``conflicting``, ``insufficient``, ``blocked``, ``absent``, and
  ``not-assessed`` NEVER map to Verified — in any combination.
- ``observed`` alone can reach Verified (direct inspection).
- Person-supplied material caps at Supported — even directly observed
  evidence, when the material was supplied rather than inspected in place
  (exports, selected files: HANDOFF M-A, "honestly marked
  Supported/Reported/Unknown, never Verified").
- The person's account (``user-reported``) caps at Reported.
- ``conflicting`` evidence yields Unknown: contradictory evidence cannot
  honestly support any level (fail closed).
- No evidence, or only claim-free states, yields Unknown.

This mapping is the shared currency of G3, G5, T7, and P1 — changing it
re-opens all four.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from capability_exchange.evidence.states import EvidenceState, coerce_state

__all__ = ["NEVER_VERIFIED_STATES", "EvidenceLevel", "evidence_level"]


class EvidenceLevel(StrEnum):
    """How a capability claim is known (Section 1.5 vocabulary, verbatim)."""

    VERIFIED = "verified"  # direct inspection
    SUPPORTED = "supported"  # person-supplied material
    REPORTED = "reported"  # person's account
    UNKNOWN = "unknown"

    def rank(self) -> int:
        """Strength order for capping only — never an aggregate score."""
        return _RANK[self]


_RANK: dict[EvidenceLevel, int] = {
    EvidenceLevel.UNKNOWN: 0,
    EvidenceLevel.REPORTED: 1,
    EvidenceLevel.SUPPORTED: 2,
    EvidenceLevel.VERIFIED: 3,
}

#: States that never map to Verified, alone or in any combination (R2).
NEVER_VERIFIED_STATES: frozenset[EvidenceState] = frozenset(
    {
        EvidenceState.STALE,
        EvidenceState.CONFLICTING,
        EvidenceState.INSUFFICIENT,
        EvidenceState.BLOCKED,
        EvidenceState.ABSENT,
        EvidenceState.NOT_ASSESSED,
    }
)

#: The strongest Level each state can contribute on its own. Total over the
#: closed vocabulary — every EvidenceState member appears exactly once, and a
#: test asserts totality by exhaustive enumeration.
_STATE_CEILING: dict[EvidenceState, EvidenceLevel] = {
    EvidenceState.OBSERVED: EvidenceLevel.VERIFIED,
    EvidenceState.USER_REPORTED: EvidenceLevel.REPORTED,
    EvidenceState.INFERRED: EvidenceLevel.SUPPORTED,
    EvidenceState.STALE: EvidenceLevel.UNKNOWN,
    EvidenceState.CONFLICTING: EvidenceLevel.UNKNOWN,
    EvidenceState.ABSENT: EvidenceLevel.UNKNOWN,
    EvidenceState.NOT_ASSESSED: EvidenceLevel.UNKNOWN,
    EvidenceState.INSUFFICIENT: EvidenceLevel.UNKNOWN,
    EvidenceState.BLOCKED: EvidenceLevel.UNKNOWN,
    EvidenceState.UNVERIFIED: EvidenceLevel.UNKNOWN,
    EvidenceState.WITHDRAWN: EvidenceLevel.UNKNOWN,
}


def evidence_level(
    states: Iterable[object],
    *,
    user_supplied_material: bool = False,
) -> EvidenceLevel:
    """Map an R2 state combination to exactly one Evidence Level. Total.

    ``states`` may contain EvidenceState members, their string values, or
    anything else — unknown/missing inputs coerce to ``not-assessed`` (which
    supports nothing) rather than raising, so the mapping never has a gap.
    Order and duplication are irrelevant: the combination is a set.

    ``user_supplied_material=True`` declares that the underlying material was
    supplied by the person (export, selected files, interview artifacts)
    rather than inspected in place by a deep adapter; such evidence caps at
    Supported and can never be Verified.
    """
    combination = frozenset(coerce_state(state) for state in states)

    if not combination:
        return EvidenceLevel.UNKNOWN

    # Fail closed: contradictory evidence supports nothing.
    if EvidenceState.CONFLICTING in combination:
        return EvidenceLevel.UNKNOWN

    # Strongest claim any present state could support on its own.
    base = max((_STATE_CEILING[state] for state in combination), key=_RANK.__getitem__)

    # Caps: degraded/deficient states in the combination forbid Verified,
    # and person-supplied material forbids Verified regardless of state.
    cap = EvidenceLevel.VERIFIED
    if combination & NEVER_VERIFIED_STATES or user_supplied_material:
        cap = EvidenceLevel.SUPPORTED

    return base if base.rank() <= cap.rank() else cap
