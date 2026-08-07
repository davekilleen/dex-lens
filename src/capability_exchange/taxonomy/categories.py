"""The nine high-impact job categories (gates.md G6; HANDOFF.md M-C).

A closed, machine-readable vocabulary: exactly these nine categories exist.
A job touching any of them is high-impact — it may be diagnosed (read-only)
but never triggers automated adaptation; the product offers only a safe
manual path or a reversible local draft.

Do not add, remove, or rename members without re-opening G6: the classifier
rules, the labeled corpus, and the evasion fixtures all key on this enum.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["HighImpactCategory"]


class HighImpactCategory(StrEnum):
    """Closed G6 vocabulary. Exactly these nine categories exist."""

    SENDING_MESSAGES = "sending-messages"
    MONEY_PURCHASING = "money-purchasing"
    PERMISSIONS = "permissions"
    DELETION = "deletion"
    CREDENTIALS = "credentials"
    HEALTH = "health"
    LEGAL = "legal"
    FINANCIAL_DECISIONS = "financial-decisions"
    THIRD_PARTY_CONFIDENTIAL_DATA = "third-party-confidential-data"
