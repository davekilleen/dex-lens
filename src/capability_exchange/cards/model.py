"""Closed, inert Capability Card data model (M5/G4/R4).

A Card is an exchange recipe for one confirmed job.  It intentionally has no
attachment, trust, executable, or self-review field.  The model is frozen and
closed; the only thing downstream code can do with its text is render or
serialize it through the disclosure boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any, Literal, Self, final

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "Card",
    "CardDependencies",
    "CardPermissions",
    "CardProvenance",
    "CardRights",
    "CardTestStatus",
    "CapabilityCard",
]

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
CARD_TEXT_MAX_LENGTH = 2048
CARD_VERSION_MAX = 1_000_000


def _bounded_text(value: str, field_name: str, *, limit: int = CARD_TEXT_MAX_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    if len(value) > limit:
        raise ValueError(f"{field_name} exceeds {limit} characters")
    if _CONTROL_RE.search(value):
        raise ValueError(f"{field_name} contains line breaks or control characters")
    return value


def _bounded_lines(value: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        value = tuple(value)
    if len(value) > 64:
        raise ValueError(f"{field_name} contains too many entries")
    return tuple(_bounded_text(item, f"{field_name} entry") for item in value)


@final
class CardPermissions(InventoriedModel):
    """The six separately grantable contribution permissions.

    ``None`` is allowed only as an unresolved value used by the local consent
    state machine.  It is never interpreted as consent: downstream lifecycle
    code treats any unresolved value as fully withdrawn.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    review: bool | None
    storage: bool | None
    moderation: bool | None
    attribution: bool | None
    reuse: bool | None
    distribution: bool | None

    @model_validator(mode="before")
    @classmethod
    def _require_all_keys(cls, value: object) -> object:
        if isinstance(value, dict):
            missing = [name for name in cls.model_fields if name not in value]
            if missing:
                raise ValueError(f"permissions missing declarations: {', '.join(missing)}")
        return value

    @property
    def is_unresolvable(self) -> bool:
        return any(value is None for value in self.model_dump(mode="python").values())

    @property
    def fully_withdrawn(self) -> bool:
        return self.is_unresolvable or not any(
            bool(value) for value in self.model_dump(mode="python").values()
        )


@final
class CardDependencies(InventoriedModel):
    """Named, non-raw dependencies a recipe expects."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[str, ...]

    @field_validator("items")
    @classmethod
    def _validate_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        result = _bounded_lines(value, "dependencies")
        if len(set(result)) != len(result):
            raise ValueError("dependencies must be unique")
        return result


@final
class CardProvenance(InventoriedModel):
    """How the recipe and claim were derived, without raw personal material."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    method_basis: str
    evidence_basis: str
    adapter_id: str
    evidence_mode: str

    @field_validator("method_basis", "evidence_basis", "adapter_id", "evidence_mode")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _bounded_text(value, info.field_name, limit=512)


@final
class CardRights(InventoriedModel):
    """Rights declaration required before moderation can approve a version."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    license_status: str
    rights_attested: bool

    @field_validator("license_status")
    @classmethod
    def _validate_license(cls, value: str) -> str:
        return _bounded_text(value, "license_status", limit=256)


class CardTestState(StrEnum):
    """Closed test-status declaration vocabulary."""

    UNTESTED = "untested"
    TESTED = "tested"
    PARTIAL = "partially-tested"
    FAILED = "failed"


@final
class CardTestStatus(InventoriedModel):
    """Evidence status for the recipe, not a trust assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: CardTestState | Literal["untested", "tested", "partially-tested", "failed"]
    summary: str

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _bounded_text(value, "test summary", limit=512)


@final
class CapabilityCard(InventoriedModel):
    """One immutable, inert Capability Card version.

    The schema is deliberately closed.  In particular, there is no field for
    attachments, raw examples, trust/review status, executable steps, or
    contributor identity.  Trust is supplied by moderation/catalog ports and
    disclosure is supplied by :mod:`capability_exchange.cards.disclosure`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str
    version: int = Field(gt=0, le=CARD_VERSION_MAX)
    selected_job: str
    method: str
    conditions: tuple[str, ...]
    desired_outcome: str
    boundaries: tuple[str, ...]
    evidence_claim: str
    permissions: CardPermissions
    dependencies: CardDependencies
    provenance: CardProvenance
    rights: CardRights
    test_status: CardTestStatus
    limitations: tuple[str, ...]

    @field_validator("card_id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _KEBAB_RE.match(value):
            raise ValueError("card_id must be kebab-case")
        return value

    @field_validator("selected_job", "method", "desired_outcome", "evidence_claim")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _bounded_text(value, info.field_name)

    @field_validator("conditions", "boundaries", "limitations")
    @classmethod
    def _validate_lines(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _bounded_lines(value, info.field_name)

    @model_validator(mode="after")
    def _require_explicit_declarations(self) -> Self:
        # Empty declarations are still explicit only where a declaration is
        # meaningful.  The Card must always state a boundary and a limitation.
        if not self.boundaries:
            raise ValueError("boundaries declaration must contain at least one limit")
        if not self.limitations:
            raise ValueError("limitations declaration must contain at least one limit")
        return self

    @property
    def version_hash(self) -> str:
        """Stable SHA-256 hash of canonical Card bytes for this version."""

        payload = self.model_dump(mode="json")
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @property
    def content_hash(self) -> str:
        return self.version_hash

    @property
    def immutable_hash(self) -> str:
        return self.version_hash

    @property
    def declared_fields(self) -> tuple[str, ...]:
        """Top-level fields that may appear in a disclosure manifest."""

        return tuple(type(self).model_fields)

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: object
    ) -> CapabilityCard:
        # ``model_construct`` skips pydantic validation.  Keep closed-schema
        # and frozen invariants intact on that adversarial route as well.
        unknown = set(values) - set(cls.model_fields)
        if unknown:
            raise ValueError(
                f"unknown Card fields are not representable: {', '.join(sorted(unknown))}"
            )
        card = super().model_construct(_fields_set, **values)  # type: ignore[arg-type]
        card._assert_closed()
        return card

    def model_copy(
        self, *, update: dict[str, object] | None = None, deep: bool = False
    ) -> CapabilityCard:
        if update:
            unknown = set(update) - set(type(self).model_fields)
            if unknown:
                raise ValueError(
                    f"unknown Card fields are not representable: {', '.join(sorted(unknown))}"
                )
        copied = super().model_copy(update=update, deep=deep)
        copied._assert_closed()
        return copied

    def _assert_closed(self) -> None:
        unknown = set(self.__dict__) - set(type(self).model_fields)
        if unknown:
            raise ValueError(
                f"unknown Card fields are not representable: {', '.join(sorted(unknown))}"
            )


# Short name used by the contribution-facing API.  It is an alias rather
# than a second model class, so the G2 inventory namespace remains unambiguous.
Card = CapabilityCard
