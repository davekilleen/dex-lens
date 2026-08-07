"""The adapter result envelope: deterministic collector output (M-A).

Adopts Doctor's grammar (HANDOFF 2.3 M-A): a deterministic collector kept
separate from any conversational renderer — this module renders nothing —
and an instrument grammar that reports failure instead of counting it as
success: ``healthy`` / ``intentionally-off`` / ``broken`` / ``could-not-check``.

**Axis warning (HANDOFF 3.2 item 2, binding):** this grammar is instrument
health, NOT Evidence Level. "Doctor's health verdict answers 'is a
probe/feature healthy?'; Evidence Level (Verified/Supported/Reported/
Unknown) answers 'how is a capability claim known?' They are different
axes; a finding needs both where relevant. Conflating them would silently
turn health into evidence." Envelope entries therefore carry R2
:class:`~capability_exchange.evidence.EvidenceItem` values for the evidence
axis, while :class:`InstrumentHealth` speaks only for the instrument.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import final

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence import EvidenceItem, supports_claims

__all__ = [
    "DETAIL_MAX_LENGTH",
    "FAILED_INSTRUMENT_HEALTHS",
    "AdapterResultEnvelope",
    "InstrumentHealth",
    "ProbeResult",
]


class InstrumentHealth(StrEnum):
    """Closed instrument grammar (Doctor's; NOT Evidence Level — see module
    docstring). Exactly these four states exist; unknown input is rejected,
    never coerced toward success."""

    HEALTHY = "healthy"  # the probe ran and its instrument is trustworthy
    INTENTIONALLY_OFF = "intentionally-off"  # off by the person's own choice
    BROKEN = "broken"  # the instrument failed; reported, never a success
    COULD_NOT_CHECK = "could-not-check"  # could not run (scope, permissions)


#: Instrument failures: reported, never counted as success.
FAILED_INSTRUMENT_HEALTHS: frozenset[InstrumentHealth] = frozenset(
    {InstrumentHealth.BROKEN, InstrumentHealth.COULD_NOT_CHECK}
)

#: A probe detail is one honest line, never a payload.
DETAIL_MAX_LENGTH = 512

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@final
class ProbeResult(InventoriedModel):
    """One probe's outcome: instrument health plus R2 evidence items.

    A failed instrument (``broken`` / ``could-not-check``) cannot carry
    claim-supporting evidence — instrument failure is never counted as
    success — and every non-healthy instrument must report why (``detail``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Kebab-case probe id, matching the contract's ``evidence_probes``.
    probe_id: str
    #: Instrument health (closed vocabulary; no default — declare it).
    health: InstrumentHealth
    #: One honest line about the instrument state; required unless healthy.
    detail: str = ""
    #: R2 evidence items collected by this probe (evidence axis).
    evidence: tuple[EvidenceItem, ...] = ()

    @field_validator("probe_id")
    @classmethod
    def _kebab_probe_id(cls, value: str) -> str:
        if not _KEBAB_RE.match(value):
            raise ValueError(f"probe_id {value!r} must be kebab-case")
        return value

    @field_validator("detail")
    @classmethod
    def _detail_is_one_bounded_line(cls, value: str) -> str:
        if len(value) > DETAIL_MAX_LENGTH:
            raise ValueError(
                f"detail exceeds {DETAIL_MAX_LENGTH} characters; a probe detail "
                f"is one honest line, never a payload"
            )
        if _CONTROL_RE.search(value):
            raise ValueError("detail contains line breaks or control characters")
        return value

    @model_validator(mode="after")
    def _failure_reported_never_success(self) -> ProbeResult:
        if self.health is not InstrumentHealth.HEALTHY and not self.detail.strip():
            raise ValueError(
                f"a {self.health.value} instrument must report why (detail); "
                f"instrument failure is reported, never silent"
            )
        if self.health in FAILED_INSTRUMENT_HEALTHS:
            for item in self.evidence:
                if supports_claims(item.state):
                    raise ValueError(
                        f"a {self.health.value} instrument cannot carry "
                        f"claim-supporting evidence ({item.state.value}); "
                        f"instrument failure is never counted as success"
                    )
        return self

    @property
    def succeeded(self) -> bool:
        """True only for a healthy instrument. Nothing else is success."""
        return self.health is InstrumentHealth.HEALTHY


@final
class AdapterResultEnvelope(InventoriedModel):
    """Deterministic collector output for one inspection run.

    Probes are canonically ordered by id and unique, so the same collection
    always serializes to the same bytes. The envelope renders nothing —
    display belongs to a separate renderer (M-D) that branches only on R2
    states and this instrument grammar.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The adapter that produced this envelope.
    adapter_id: str
    #: The contract version the collection ran under.
    contract_version: str
    #: When collection happened (timezone-aware; naive is unverifiable).
    collected_at: datetime
    #: Per-probe results; canonically sorted, at least one (an empty
    #: envelope would imply a clean bill nobody checked for).
    probes: tuple[ProbeResult, ...] = Field(min_length=1)

    @field_validator("adapter_id")
    @classmethod
    def _kebab_adapter_id(cls, value: str) -> str:
        if not _KEBAB_RE.match(value):
            raise ValueError(f"adapter_id {value!r} must be kebab-case")
        return value

    @field_validator("contract_version")
    @classmethod
    def _semver_version(cls, value: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+$", value):
            raise ValueError(f"contract_version {value!r} must be MAJOR.MINOR.PATCH")
        return value

    @field_validator("collected_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "collected_at must be timezone-aware; a naive timestamp is an "
                "unverifiable collection time (fail closed)"
            )
        return value

    @field_validator("probes")
    @classmethod
    def _unique_and_canonically_ordered(
        cls, value: tuple[ProbeResult, ...]
    ) -> tuple[ProbeResult, ...]:
        ids = [probe.probe_id for probe in value]
        if len(set(ids)) != len(ids):
            raise ValueError("probes contain duplicate probe ids")
        return tuple(sorted(value, key=lambda probe: probe.probe_id))

    @property
    def successful_probes(self) -> tuple[ProbeResult, ...]:
        """Healthy instruments only. Failure is never in this tuple."""
        return tuple(p for p in self.probes if p.health is InstrumentHealth.HEALTHY)

    @property
    def reported_failures(self) -> tuple[ProbeResult, ...]:
        """Instrument failures, reported as such (broken / could-not-check)."""
        return tuple(p for p in self.probes if p.health in FAILED_INSTRUMENT_HEALTHS)

    def health_counts(self) -> dict[InstrumentHealth, int]:
        """Total count per instrument-health state (bounded status data)."""
        counts = dict.fromkeys(InstrumentHealth, 0)
        for probe in self.probes:
            counts[probe.health] += 1
        return counts
