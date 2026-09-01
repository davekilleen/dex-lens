"""Closed, secret-safe observations of a personal AI system.

Operational state is deliberately separate from :class:`EvidenceState`.
Evidence says how a claim was learned; operational state says how far the
observed capability has progressed from declaration to a verified outcome.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.provenance import SourceClass, SourceProvenance
from capability_exchange.evidence import EvidenceItem

__all__ = [
    "EvidenceFingerprint",
    "ConfigurationState",
    "ConfiguredState",
    "HealthState",
    "Observation",
    "ObservationKind",
    "OperationalState",
    "RuntimeState",
    "RunningState",
    "SafeAttribute",
    "SourceProvenance",
    "migrate_stored_fingerprint_payload",
    "migrate_stored_observation_payload",
    "observation_id_for",
    "observation_key_for",
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
        "live-state-match",
    }
)
_SECRET_SHAPED_MARKERS = ("token", "secret", "password", "credential")


class OperationalState(StrEnum):
    """Legacy collapsed state accepted only at compatibility boundaries.

    New observations persist three independent axis values instead.  Keeping
    this vocabulary for one release lets old callers construct an observation
    while ensuring the serialized model has no second, competing truth.
    """

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


class ConfigurationState(StrEnum):
    """What the approved snapshot proves about configuration or installation."""

    ABSENT = "absent"
    DECLARED = "declared"
    IMPLEMENTED = "implemented"
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    CONFLICTING = "conflicting"
    NOT_ASSESSED = "not-assessed"
    UNSUPPORTED = "unsupported"


# The shorter spelling is useful to consumers that call the first axis
# "configured".  It is an alias, not another runtime model or vocabulary.
ConfiguredState = ConfigurationState


class RuntimeState(StrEnum):
    """What a live/read-only check proves about execution."""

    ABSENT = "absent"
    DISABLED = "disabled"
    LOADED = "loaded"
    RUNNING = "running"
    RECENTLY_RUN = "recently-run"
    OUTCOME_VERIFIED = "outcome-verified"
    STALE = "stale"
    CONFLICTING = "conflicting"
    NOT_ASSESSED = "not-assessed"
    UNSUPPORTED = "unsupported"


RunningState = RuntimeState


class HealthState(StrEnum):
    """What an explicit health check proves, independent of configuration."""

    ABSENT = "absent"
    DISABLED = "disabled"
    HEALTHY = "healthy"
    BROKEN = "broken"
    STALE = "stale"
    CONFLICTING = "conflicting"
    NOT_ASSESSED = "not-assessed"
    UNSUPPORTED = "unsupported"


def _axes_for_operational_state(
    value: OperationalState | str,
) -> tuple[ConfigurationState, RuntimeState, HealthState]:
    """Translate one pre-axis state into honest independent evidence axes."""

    state = OperationalState(value)
    not_assessed = (
        ConfigurationState.NOT_ASSESSED,
        RuntimeState.NOT_ASSESSED,
        HealthState.NOT_ASSESSED,
    )
    mapping: dict[OperationalState, tuple[ConfigurationState, RuntimeState, HealthState]] = {
        OperationalState.DECLARED: (
            ConfigurationState.DECLARED,
            RuntimeState.NOT_ASSESSED,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.IMPLEMENTED: (
            ConfigurationState.IMPLEMENTED,
            RuntimeState.NOT_ASSESSED,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.INSTALLED: (
            ConfigurationState.INSTALLED,
            RuntimeState.NOT_ASSESSED,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.ENABLED: (
            ConfigurationState.ENABLED,
            RuntimeState.NOT_ASSESSED,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.LOADED: (
            ConfigurationState.ENABLED,
            RuntimeState.LOADED,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.RECENTLY_RUN: (
            ConfigurationState.ENABLED,
            RuntimeState.RECENTLY_RUN,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.OUTCOME_VERIFIED: (
            ConfigurationState.ENABLED,
            RuntimeState.OUTCOME_VERIFIED,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.DISABLED: (
            ConfigurationState.DISABLED,
            RuntimeState.DISABLED,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.STALE: (
            ConfigurationState.ENABLED,
            RuntimeState.STALE,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.CONFLICTING: (
            ConfigurationState.CONFLICTING,
            RuntimeState.CONFLICTING,
            HealthState.CONFLICTING,
        ),
        OperationalState.ABSENT: (
            ConfigurationState.ABSENT,
            RuntimeState.NOT_ASSESSED,
            HealthState.NOT_ASSESSED,
        ),
        OperationalState.UNSUPPORTED: (
            ConfigurationState.UNSUPPORTED,
            RuntimeState.UNSUPPORTED,
            HealthState.UNSUPPORTED,
        ),
    }
    return mapping.get(state, not_assessed)


def _legacy_state_for_axes(
    configuration_state: ConfigurationState,
    runtime_state: RuntimeState,
    health_state: HealthState,
) -> OperationalState:
    """Project axes for old in-memory callers without persisting the scalar."""

    if health_state is HealthState.CONFLICTING or runtime_state is RuntimeState.CONFLICTING:
        return OperationalState.CONFLICTING
    if runtime_state is RuntimeState.OUTCOME_VERIFIED:
        return OperationalState.OUTCOME_VERIFIED
    if runtime_state is RuntimeState.RECENTLY_RUN:
        return OperationalState.RECENTLY_RUN
    if runtime_state is RuntimeState.LOADED:
        return OperationalState.LOADED
    if runtime_state is RuntimeState.STALE:
        return OperationalState.STALE
    if runtime_state is RuntimeState.DISABLED:
        return OperationalState.DISABLED
    if configuration_state is ConfigurationState.DISABLED:
        return OperationalState.DISABLED
    if configuration_state is ConfigurationState.ABSENT:
        return OperationalState.ABSENT
    if configuration_state is ConfigurationState.UNSUPPORTED:
        return OperationalState.UNSUPPORTED
    if configuration_state is ConfigurationState.ENABLED:
        return OperationalState.ENABLED
    if configuration_state is ConfigurationState.INSTALLED:
        return OperationalState.INSTALLED
    if configuration_state is ConfigurationState.IMPLEMENTED:
        return OperationalState.IMPLEMENTED
    if configuration_state is ConfigurationState.DECLARED:
        return OperationalState.DECLARED
    return OperationalState.NOT_ASSESSED


_AXIS_FIELD_NAMES = frozenset({"configuration_state", "runtime_state", "health_state"})
_LEGACY_MISSING = object()


def _normalise_observation_input(values: Mapping[str, object]) -> dict[str, object]:
    """Accept constructor aliases and map the scalar only at old call sites."""

    normalised = dict(values)
    aliases = {
        "configured": "configuration_state",
        "configured_state": "configuration_state",
        "configuration": "configuration_state",
        "runtime": "runtime_state",
        "running": "runtime_state",
        "running_state": "runtime_state",
        "health": "health_state",
        "healthy": "health_state",
    }
    for alias, canonical in aliases.items():
        if alias in normalised:
            if canonical in normalised and normalised[canonical] != normalised[alias]:
                raise ValueError(f"observation supplied competing {canonical} values")
            normalised[canonical] = normalised.pop(alias)
    if "operational_state" in normalised and _AXIS_FIELD_NAMES & normalised.keys():
        raise ValueError("observation cannot contain operational_state alongside axis fields")
    legacy = normalised.pop("operational_state", _LEGACY_MISSING)
    if legacy is not _LEGACY_MISSING:
        configuration_state, runtime_state, health_state = _axes_for_operational_state(legacy)
        normalised.update(
            {
                "configuration_state": configuration_state,
                "runtime_state": runtime_state,
                "health_state": health_state,
            }
        )
    return normalised


class ObservationKind(StrEnum):
    """Closed classes of system evidence Lens may retain."""

    RELEASE = "release"
    SKILL = "skill"
    MCP_SERVER = "mcp-server"
    MCP_TOOL = "mcp-tool"
    AUTOMATION = "automation"
    HOOK = "hook"
    INTEGRATION_REGISTRY = "integration-registry"
    INTEGRATION_PROVIDER = "integration-provider"
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

    def copy(self, **kwargs: object) -> Self:
        """Block Pydantic's deprecated, validation-bypassing copy route."""

        raise TypeError("copy() is disabled for SafeAttribute; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Keep attribute validators active on the supported copy route."""

        values = {field_name: getattr(self, field_name) for field_name in type(self).model_fields}
        if update:
            values.update(update)
        return type(self).model_validate(values)

    @classmethod
    def model_construct(
        cls,
        _fields_set: set[str] | None = None,
        **values: object,
    ) -> Self:
        """Keep attribute validators active on the construct route."""

        return cls.model_validate(values)


class Observation(InventoriedModel):
    """One bounded system fact with independent configuration/runtime/health axes.

    ``operational_state`` remains a compatibility-only constructor/property
    for callers written against the pre-axis model.  It is intentionally not
    a pydantic field and therefore never appears in a stored or transmitted
    payload.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def __init__(self, **data: object) -> None:
        # Existing adapters and fixtures construct observations directly with
        # ``operational_state``.  Translate that legacy input before Pydantic
        # sees it; model validation of stored dictionaries remains strict and
        # must pass through ``migrate_stored_observation_payload`` explicitly.
        super().__init__(**_normalise_observation_input(data))

    kind: ObservationKind
    identity: str
    label: str = Field(min_length=1, max_length=160)
    configuration_state: ConfigurationState = Field(
        validation_alias=AliasChoices(
            "configuration_state",
            "configured_state",
            "configured",
            "configuration",
        )
    )
    runtime_state: RuntimeState = Field(
        validation_alias=AliasChoices("runtime_state", "runtime", "running_state", "running")
    )
    health_state: HealthState = Field(
        validation_alias=AliasChoices("health_state", "health", "healthy")
    )
    evidence: EvidenceItem
    provenance: SourceProvenance
    attributes: tuple[SafeAttribute, ...] = ()

    @field_validator("identity")
    @classmethod
    def _identity_shape(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError("observation identity must be a bounded stable id")
        return value

    @model_validator(mode="after")
    def _working_copy_is_not_assessed(self) -> Self:
        if self.provenance.source_class is SourceClass.WORKING_COPY:
            object.__setattr__(
                self,
                "configuration_state",
                ConfigurationState.NOT_ASSESSED,
            )
            object.__setattr__(
                self,
                "runtime_state",
                RuntimeState.NOT_ASSESSED,
            )
            object.__setattr__(
                self,
                "health_state",
                HealthState.NOT_ASSESSED,
            )
        return self

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Keep nested provenance validation active on the copy route."""

        if update and "provenance" in update:
            replacement = SourceProvenance.model_validate(update["provenance"])
            if replacement != self.provenance:
                raise ValueError("observation provenance is locked after construction")
        values = {field_name: getattr(self, field_name) for field_name in type(self).model_fields}
        if update:
            values.update(update)
        return type(self)(**_normalise_observation_input(values))

    @property
    def configured(self) -> ConfigurationState:
        """Short alias for the configuration axis."""

        return self.configuration_state

    @property
    def configured_state(self) -> ConfigurationState:
        """Compatibility alias for consumers that name the axis configured."""

        return self.configuration_state

    @property
    def runtime(self) -> RuntimeState:
        """Short alias for the runtime axis."""

        return self.runtime_state

    @property
    def running(self) -> RuntimeState:
        """Readable alias for the runtime axis."""

        return self.runtime_state

    @property
    def health(self) -> HealthState:
        """Short alias for the health axis."""

        return self.health_state

    @property
    def healthy(self) -> HealthState:
        """Readable alias for the health axis."""

        return self.health_state

    @property
    def operational_state(self) -> OperationalState:
        """Project axes for legacy in-memory readers; never serialized."""

        # The old scalar could not represent a configured capability whose
        # live match was ambiguous across approved sources.  Keep that legacy
        # projection conservative while the persisted axes retain the
        # independently known configuration fact.
        if any(
            attribute.key == "live-state-match"
            and attribute.value == "ambiguous-across-approved-sources"
            for attribute in self.attributes
        ):
            return OperationalState.NOT_ASSESSED

        return _legacy_state_for_axes(
            self.configuration_state,
            self.runtime_state,
            self.health_state,
        )

    @property
    def observation_id(self) -> str:
        """Stable digest identity for this observation's source-bound fact."""

        return observation_id_for(self)

    @property
    def observation_key(self) -> str:
        """Readable source-bound key retained for backwards-compatible evidence tokens."""

        return observation_key_for(self)

    def copy(self, **kwargs: object) -> Self:
        """Block Pydantic's deprecated, validation-bypassing copy route."""

        raise TypeError("copy() is disabled for Observation; use validated model_copy()")

    @classmethod
    def model_construct(
        cls,
        _fields_set: set[str] | None = None,
        **values: object,
    ) -> Self:
        """Keep nested provenance validation active on the construct route."""

        return cls(**_normalise_observation_input(values))


def migrate_stored_observation_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Migrate one pre-axis stored observation without writing anything.

    The migration is deliberately a pure, one-way boundary operation.  New
    payloads must carry all three axis fields and may not carry the old scalar;
    old payloads carry only ``operational_state`` and are translated once.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("stored observation payload must be a mapping")
    migrated = dict(payload)
    legacy = migrated.pop("operational_state", _LEGACY_MISSING)
    present = _AXIS_FIELD_NAMES & migrated.keys()
    if legacy is not _LEGACY_MISSING:
        if present:
            raise ValueError(
                "stored observation cannot contain operational_state alongside axis fields"
            )
        try:
            configuration_state, runtime_state, health_state = _axes_for_operational_state(legacy)
        except (TypeError, ValueError) as exc:
            raise ValueError("stored observation operational_state is not recognised") from exc
        migrated.update(
            {
                "configuration_state": configuration_state.value,
                "runtime_state": runtime_state.value,
                "health_state": health_state.value,
            }
        )
    elif present != _AXIS_FIELD_NAMES:
        raise ValueError(
            "stored observation must contain either operational_state or all three axis fields"
        )
    return migrated


def migrate_stored_fingerprint_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Read one stored fingerprint through the single legacy-axis migration."""

    if not isinstance(payload, Mapping):
        raise ValueError("stored fingerprint payload must be a mapping")
    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, Sequence) or isinstance(
        raw_observations, (str, bytes, bytearray)
    ):
        raise ValueError("stored fingerprint observations must be a sequence")
    migrated = dict(payload)
    migrated["observations"] = [
        migrate_stored_observation_payload(item)
        if isinstance(item, Mapping)
        else (_raise_invalid_observation_payload())
        for item in raw_observations
    ]
    return migrated


def _raise_invalid_observation_payload() -> dict[str, object]:
    """Raise from a list expression while retaining a precise migration error."""

    raise ValueError("stored fingerprint observation must be a mapping")


class EvidenceFingerprint(InventoriedModel):
    """Ephemeral, local-only inventory produced from approved read scopes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_id: str
    collected_at: datetime
    observations: tuple[Observation, ...]
    limits: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _unique_observations(self) -> Self:
        keys = [(item.kind, item.identity, item.provenance.source_id) for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("fingerprint contains a duplicate observation")
        return self

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Revalidate the complete fingerprint on every copy route."""

        values = {field_name: getattr(self, field_name) for field_name in type(self).model_fields}
        if update:
            values.update(update)
        return type(self).model_validate(values)

    def copy(self, **kwargs: object) -> Self:
        """Block Pydantic's deprecated, validation-bypassing copy route."""

        raise TypeError("copy() is disabled for EvidenceFingerprint; use validated model_copy()")

    @classmethod
    def model_construct(
        cls,
        _fields_set: set[str] | None = None,
        **values: object,
    ) -> Self:
        """Revalidate the complete fingerprint on the construct route."""

        return cls.model_validate(values)


def observation_key_for(observation: Observation) -> str:
    """Return the legacy readable key for one source-bound observation."""

    return (
        f"{observation.kind.value}:{observation.identity}:"
        f"{observation.provenance.source_id}"
    )


def observation_id_for(observation: Observation) -> str:
    """Return a stable, opaque identity for one exact observation.

    The source-bound tuple is digested so labels, paths and provider metadata
    never become an identity that can leak across the local boundary.
    """

    from capability_exchange.diagnosis.run import canonical_json_digest

    return "observation:" + canonical_json_digest(
        {
            "identity": observation.identity,
            "kind": observation.kind.value,
            "source_id": observation.provenance.source_id,
        }
    )
