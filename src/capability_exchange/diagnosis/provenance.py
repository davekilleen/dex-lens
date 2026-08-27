"""Closed, non-raw source provenance for diagnosis observations."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.boundary.secret_markers import has_secret_shape_marker
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence.item import reference_rejection_reason

__all__ = [
    "SourceClass",
    "SourceProvenance",
    "relative_reference_rejection_reason",
]

_HOME_SEGMENTS = frozenset({"$home", "${home}", "$userprofile", "${userprofile}", "%userprofile%"})


def relative_reference_rejection_reason(value: str) -> str | None:
    """Explain why a source-relative locator cannot cross the trust boundary."""

    normalized = value.replace("\\", "/")
    segments = normalized.split("/")
    first = segments[0].lower()
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        return "relative_reference must not be an absolute path"
    if first.startswith("~") or first in _HOME_SEGMENTS:
        return "relative_reference must not contain a home prefix"
    if ".." in segments:
        return "relative_reference must not traverse its approved source"
    if any(unicodedata.category(char) == "Cc" for char in value):
        return "relative_reference must not contain control characters"
    reason = reference_rejection_reason(value)
    if reason is not None:
        return f"relative_reference is not a safe locator: {reason}"
    if has_secret_shape_marker(value):
        return "relative_reference must not contain secret-shaped markers"
    return None


class SourceClass(StrEnum):
    """Closed ownership classes approved at consent time."""

    VAULT_AUTHORED = "vault-authored"
    USER_GLOBAL = "user-global"
    HARNESS_BUNDLED = "harness-bundled"
    PLUGIN_OR_VENDOR = "plugin-or-vendor"
    WORKING_COPY = "working-copy"
    GENERATED = "generated"
    LIVE_SYSTEM = "live-system"


class SourceProvenance(InventoriedModel):
    """One immutable, non-raw source locator carried by an observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(pattern=r"^scope:[a-z0-9._-]{3,120}$")
    source_class: SourceClass
    scope_reference: str = Field(pattern=r"^scope:sha256:[0-9a-f]{64}$")
    relative_reference: str = Field(min_length=1, max_length=240)
    content_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )

    @field_validator("relative_reference")
    @classmethod
    def _relative_non_raw_reference(cls, value: str) -> str:
        reason = relative_reference_rejection_reason(value)
        if reason is not None:
            raise ValueError(reason)
        return value

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Keep every provenance validator active on Pydantic's copy route."""

        values = {field_name: getattr(self, field_name) for field_name in type(self).model_fields}
        if update:
            values.update(update)
        return type(self).model_validate(values)

    def copy(self, **kwargs: object) -> Self:
        """Block Pydantic's deprecated, validation-bypassing copy route."""

        raise TypeError("copy() is disabled for SourceProvenance; use validated model_copy()")

    @classmethod
    def model_construct(
        cls,
        _fields_set: set[str] | None = None,
        **values: object,
    ) -> Self:
        """Keep every provenance validator active on the construct route."""

        return cls.model_validate(values)
