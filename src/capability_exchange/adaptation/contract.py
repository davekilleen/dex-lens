"""Closed M4 mutation contract and guarantee vocabulary.

An adapter is Adapt-capable only when a named operation is structurally
allowlisted and all six guarantees needed by T1–T9 are present.  Declarations
do not themselves prove a guarantee; the conformance matrix validates each
one before the adapter contract may expose the operation.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "REQUIRED_GUARANTEES",
    "Guarantee",
    "MutationContract",
    "OperationKind",
]

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class OperationKind(StrEnum):
    """Closed operation vocabulary for the pilot allowlist.

    The single member is create-only and user-owned.  Sending, deleting,
    overwriting, permission/credential changes, publishing, purchasing,
    security weakening, networking, and external-system changes have no
    member and therefore cannot be constructed by the transaction engine.
    """

    CREATE_NAMESPACED_SKILL = "create-namespaced-skill"


class Guarantee(StrEnum):
    """Guarantees every Adapt-capable operation must prove."""

    PREVIEW_IDENTITY = "preview-identity"
    RECOVERY = "recovery"
    OWNERSHIP = "ownership"
    RECEIPT = "receipt"
    VERIFICATION = "verification"
    UNDO = "undo"


REQUIRED_GUARANTEES: tuple[Guarantee, ...] = tuple(Guarantee)


class MutationContract(InventoriedModel):
    """Immutable host mutation declaration held to the T1–T9 matrix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_id: str
    contract_version: str
    operations: tuple[OperationKind, ...] = Field(min_length=1)
    guarantees: tuple[Guarantee, ...] = Field(min_length=1)

    @field_validator("contract_id")
    @classmethod
    def _contract_id_is_kebab_case(cls, value: str) -> str:
        if not _KEBAB_RE.fullmatch(value):
            raise ValueError("contract_id must be kebab-case")
        return value

    @field_validator("contract_version")
    @classmethod
    def _contract_version_is_semver(cls, value: str) -> str:
        if not _SEMVER_RE.fullmatch(value):
            raise ValueError("contract_version must be MAJOR.MINOR.PATCH")
        return value

    @model_validator(mode="after")
    def _complete_and_unique(self) -> MutationContract:
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("operations contains a duplicate")
        if len(set(self.guarantees)) != len(self.guarantees):
            raise ValueError("guarantees contains a duplicate")
        missing = tuple(item for item in REQUIRED_GUARANTEES if item not in self.guarantees)
        if missing:
            joined = ", ".join(item.value for item in missing)
            raise ValueError(f"Adapt-capable contract is missing guarantee(s): {joined}")
        return self

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: Any
    ) -> MutationContract:
        """Keep the guarantee wall intact on pydantic's unsafe constructor."""

        del _fields_set
        return cls.model_validate(values)
