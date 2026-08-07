"""EvidenceItem: state + source age + non-raw reference (gates.md R2).

Every evidence item carries its R2 state, its source age (a timezone-aware
capture timestamp plus an optional staleness threshold), and a reference.

A reference is a locator or digest — a pointer under the G2 field-level data
boundary — never a payload. Validation rejects references that look like raw
file content (the R2 hostile fixture), because a raw payload smuggled into a
reference field would cross the data boundary uninventoried.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, field_validator

from capability_exchange.evidence.states import EvidenceState, coerce_state

__all__ = ["REFERENCE_MAX_LENGTH", "EvidenceItem"]

#: A locator/digest fits comfortably in this bound; raw file content rarely does.
REFERENCE_MAX_LENGTH = 512

#: Newlines, carriage returns, and control characters mark multi-line or
#: binary payloads, never locators.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

#: Key material / secret-block markers: payloads, never references.
_PAYLOAD_MARKERS = ("-----BEGIN",)

#: A long run of whitespace-separated words is prose (file content), not a
#: locator. Locators (paths, digests, probe ids) have few word breaks.
_MAX_REFERENCE_WORDS = 8


def _looks_like_raw_content(reference: str) -> str | None:
    """Return a rejection reason if the reference looks like a payload."""
    if len(reference) > REFERENCE_MAX_LENGTH:
        return (
            f"reference exceeds {REFERENCE_MAX_LENGTH} characters; "
            "a reference is a locator/digest, never a payload"
        )
    if _CONTROL_CHARS.search(reference):
        return (
            "reference contains line breaks or control characters; "
            "raw file content is not a reference"
        )
    for marker in _PAYLOAD_MARKERS:
        if marker in reference:
            return (
                "reference contains key/secret block markers; raw content is never "
                "stored, referenced material must be redacted at collection"
            )
    if len(reference.split()) > _MAX_REFERENCE_WORDS:
        return "reference reads as prose; a reference is a locator/digest, never file content"
    return None


class EvidenceItem(BaseModel):
    """One piece of evidence for a capability claim.

    Read-only data (frozen, closed schema): the diagnosis side never holds a
    write capability, and no field outside this schema is representable
    (G2 posture: uninventoried fields are unrepresentable, not filtered).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: R2 state. Missing/unknown input fails closed to ``not-assessed``.
    state: EvidenceState = EvidenceState.NOT_ASSESSED

    #: When the evidence was captured. Timezone-aware, required: a naive
    #: timestamp is an unverifiable source age and is rejected (fail closed).
    captured_at: datetime

    #: Optional freshness threshold. Evidence older than this degrades to
    #: ``stale`` automatically rather than remaining silently trusted (R2).
    stale_after: timedelta | None = None

    #: Non-raw reference: a locator or digest, never a payload.
    reference: str

    @field_validator("state", mode="before")
    @classmethod
    def _coerce_state(cls, value: object) -> EvidenceState:
        return coerce_state(value)

    @field_validator("captured_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "captured_at must be timezone-aware; a naive timestamp is an "
                "unverifiable source age (fail closed)"
            )
        return value

    @field_validator("reference")
    @classmethod
    def _reject_raw_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reference must be a non-empty locator or digest")
        reason = _looks_like_raw_content(value)
        if reason is not None:
            raise ValueError(reason)
        return value

    def age(self, *, now: datetime) -> timedelta:
        """Source age at ``now``. Negative means a claimed future capture."""
        return now - self.captured_at

    def effective_state(self, *, now: datetime) -> EvidenceState:
        """The state after applying source-age rules at ``now``.

        Fail closed:

        - a capture timestamp in the future is an unverifiable age →
          ``not-assessed`` (supports nothing);
        - claim-supporting evidence older than ``stale_after`` degrades to
          ``stale`` automatically (R2) — it is never silently trusted.

        Terminal/degraded states (``absent``, ``withdrawn``, ``blocked``, …)
        already support no claim and pass through unchanged.
        """
        if self.age(now=now) < timedelta(0):
            return EvidenceState.NOT_ASSESSED
        if (
            self.stale_after is not None
            and self.age(now=now) > self.stale_after
            and self.state
            in (EvidenceState.OBSERVED, EvidenceState.USER_REPORTED, EvidenceState.INFERRED)
        ):
            return EvidenceState.STALE
        return self.state
