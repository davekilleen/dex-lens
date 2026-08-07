"""The closed R2 evidence-state vocabulary (gates.md R2; HANDOFF.md M-B).

Evidence and findings use exactly this closed, machine-readable vocabulary.
All downstream logic (diagnosis display, adaptation eligibility, pilot
analysis) branches only on these states.

Fail closed: a missing or unknown state coerces to `not-assessed`, and
`not-assessed` evidence supports no diagnosis claim, no adaptation
eligibility, and no pilot success.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CLAIM_SUPPORTING_STATES",
    "EvidenceState",
    "coerce_state",
    "supports_claims",
]


class EvidenceState(StrEnum):
    """Closed R2 vocabulary. Exactly these eleven states exist.

    Do not add members without re-opening G3, G5, T7, and P1 — this
    vocabulary is their shared currency (gates.md, closing note).
    """

    OBSERVED = "observed"  # directly inspected under the approved scope
    USER_REPORTED = "user-reported"  # the person's own account
    INFERRED = "inferred"  # derived/concluded, never direct observation
    STALE = "stale"  # older than the declared freshness threshold
    CONFLICTING = "conflicting"  # contradicted by other evidence
    ABSENT = "absent"  # looked for, verifiably not there
    NOT_ASSESSED = "not-assessed"  # never evaluated; also the fail-closed sink
    INSUFFICIENT = "insufficient"  # evaluated, but not enough to support a claim
    BLOCKED = "blocked"  # collection prevented (permissions, containment)
    UNVERIFIED = "unverified"  # verification attempted, outcome uncertain (G3/T7)
    WITHDRAWN = "withdrawn"  # previously held, explicitly retracted


_BY_NORMALIZED_VALUE: dict[str, EvidenceState] = {
    member.value: member for member in EvidenceState
}


def coerce_state(value: object) -> EvidenceState:
    """Coerce any input to a member of the closed vocabulary. Total; never raises.

    Accepts EvidenceState members and their string values, tolerating case,
    surrounding whitespace, and ``_``/space separators (``user_reported`` →
    ``user-reported``). Anything else — ``None``, unknown strings, non-string
    garbage — fails closed to :data:`EvidenceState.NOT_ASSESSED`, which
    supports nothing.
    """
    if isinstance(value, EvidenceState):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
        found = _BY_NORMALIZED_VALUE.get(normalized)
        if found is not None:
            return found
    return EvidenceState.NOT_ASSESSED


#: The only states that can support a capability claim at all — i.e. raise a
#: finding's Evidence Level above Unknown. Everything else supports nothing.
CLAIM_SUPPORTING_STATES: frozenset[EvidenceState] = frozenset(
    {EvidenceState.OBSERVED, EvidenceState.USER_REPORTED, EvidenceState.INFERRED}
)


def supports_claims(state: EvidenceState) -> bool:
    """Whether evidence in this state can support any diagnosis claim.

    ``not-assessed``, ``absent``, and every degraded or terminal state
    support nothing: they never display or count as passing (R2).
    """
    return state in CLAIM_SUPPORTING_STATES
