"""Closed, secret-safe observations of a personal AI system.

Operational state is deliberately separate from :class:`EvidenceState`.
Evidence says how a claim was learned; operational state says how far the
observed capability has progressed from declaration to a verified outcome.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence import EvidenceItem

__all__ = [
    "EvidenceFingerprint",
    "Observation",
    "ObservationKind",
    "OperationalState",
    "SafeAttribute",
]

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
_SAFE_ATTRIBUTE_KEYS = frozenset(
    {
        "transport",
        "tool-count",
        "config-scope",
        "schedule",
        "run-at-load",
        "hook-event",
        "release-id",
        "source-kind",
        "provider-count",
        "receipt-age",
    }
)
_SECRET_SHAPED_MARKERS = ("token", "secret", "password", "credential")


class OperationalState(StrEnum):
    """How far an observed capability is proved to operate."""

    DECLARED = "declared"
    IMPLEMENTED = "implemented"
    INSTALLED = "installed"
    ENABLED = "enabled"
    LOADED = "loaded"
    RECENTLY_RUN = "recently-run"
    OUTCOME_VERIFIED = "outcome-verified"
    DISABLED = "disabled"
    STALE = "stale"
    CONFLICTING = "conflicting"
    ABSENT = "absent"
    NOT_ASSESSED = "not-assessed"
    UNSUPPORTED = "unsupported"


class ObservationKind(StrEnum):
    """Closed classes of system evidence Lens may retain."""

    RELEASE = "release"
    SKILL = "skill"
    MCP_SERVER = "mcp-server"
    MCP_TOOL = "mcp-tool"
    AUTOMATION = "automation"
    HOOK = "hook"
    INTEGRATION_REGISTRY = "integration-registry"
    HEALTH_CHECK = "health-check"
    RECOVERY_PROOF = "recovery-proof"


class SafeAttribute(InventoriedModel):
    """One allowlisted, bounded fact that cannot retain raw private content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    value: str = Field(min_length=1, max_length=160)

    @field_validator("key")
    @classmethod
    def _allowlisted_key(cls, value: str) -> str:
        if value not in _SAFE_ATTRIBUTE_KEYS:
            raise ValueError(f"attribute key {value!r} is not allowlisted")
        return value

    @field_validator("value")
    @classmethod
    def _single_safe_line(cls, value: str) -> str:
        lowered = value.lower()
        if any(marker in lowered for marker in _SECRET_SHAPED_MARKERS):
            raise ValueError("attribute values may not carry secret-shaped material")
        if "\n" in value or "\r" in value:
            raise ValueError("attribute values are one bounded line")
        return value


class Observation(InventoriedModel):
    """One bounded system fact and the evidence supporting it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ObservationKind
    identity: str
    label: str = Field(min_length=1, max_length=160)
    operational_state: OperationalState
    evidence: EvidenceItem
    attributes: tuple[SafeAttribute, ...] = ()

    @field_validator("identity")
    @classmethod
    def _identity_shape(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError("observation identity must be a bounded stable id")
        return value


class EvidenceFingerprint(InventoriedModel):
    """Ephemeral, local-only inventory produced from approved read scopes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_id: str
    collected_at: datetime
    observations: tuple[Observation, ...]
    limits: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _unique_observations(self) -> Self:
        keys = [(item.kind, item.identity) for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("fingerprint contains a duplicate observation")
        return self
