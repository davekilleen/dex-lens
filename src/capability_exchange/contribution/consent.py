"""Per-version contribution consent and six-permission lifecycle (G4)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import final

from pydantic import ConfigDict

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.cards.disclosure import DisclosureManifest
from capability_exchange.cards.model import CapabilityCard
from capability_exchange.cards.validation import CardValidationError, require_valid_card

__all__ = [
    "ConsentError",
    "ConsentLedger",
    "ConsentRecord",
    "Permission",
    "PermissionSet",
    "VersionConsent",
]


class ConsentError(ValueError):
    """Consent is absent, stale, withdrawn, or mismatched to the manifest."""


class Permission(StrEnum):
    REVIEW = "review"
    STORAGE = "storage"
    MODERATION = "moderation"
    ATTRIBUTION = "attribution"
    REUSE = "reuse"
    DISTRIBUTION = "distribution"


@final
class PermissionSet(InventoriedModel):
    """Six independently grantable permissions.

    ``None`` means the person/system could not resolve the state.  It is not a
    default and is fail-closed as fully withdrawn by lifecycle code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    review: bool | None
    storage: bool | None
    moderation: bool | None
    attribution: bool | None
    reuse: bool | None
    distribution: bool | None

    @property
    def granted(self) -> frozenset[Permission]:
        return frozenset(
            Permission(name)
            for name, value in self.model_dump(mode="python").items()
            if value is True
        )

    @property
    def all_granted(self) -> bool:
        return not self.is_unresolvable and len(self.granted) == len(Permission)

    @property
    def is_unresolvable(self) -> bool:
        return any(value is None for value in self.model_dump(mode="python").values())

    @property
    def fully_withdrawn(self) -> bool:
        return self.is_unresolvable or not bool(self.granted)

    def allows(self, permission: Permission) -> bool:
        return bool(getattr(self, permission.value))

    def revoke(self, permission: Permission) -> PermissionSet:
        """Return a new immutable permission snapshot with one grant revoked."""

        return self.model_copy(update={permission.value: False})

    def withdraw_all(self) -> PermissionSet:
        return PermissionSet(
            review=False,
            storage=False,
            moderation=False,
            attribution=False,
            reuse=False,
            distribution=False,
        )


@final
class ConsentRecord(InventoriedModel):
    """Immutable consent for exactly one Card version + disclosure manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str
    card_version_hash: str
    manifest_hash: str
    permissions: PermissionSet
    consented_at: datetime
    withdrawn: bool = False

    @classmethod
    def now(
        cls,
        card: CapabilityCard,
        manifest: DisclosureManifest,
        permissions: PermissionSet,
    ) -> ConsentRecord:
        require_valid_card(card)
        return cls(
            card_id=card.card_id,
            card_version_hash=card.version_hash,
            manifest_hash=manifest.byte_hash,
            permissions=permissions,
            consented_at=datetime.now(UTC),
        )


class ConsentLedger:
    """Local, in-memory consent records keyed by immutable version hash."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ConsentRecord] = {}

    def grant(
        self,
        card: CapabilityCard,
        manifest: DisclosureManifest,
        permissions: PermissionSet,
    ) -> ConsentRecord:
        try:
            require_valid_card(card)
        except CardValidationError as exc:
            raise ConsentError(
                "Card validation failed before consent: " + ", ".join(exc.reason_codes)
            ) from exc
        if not manifest.verify_card(card):
            raise ConsentError("disclosure manifest does not match this Card version")
        if not card.rights.rights_attested:
            raise ConsentError("rights attestation is required before version consent")
        record = ConsentRecord.now(card, manifest, permissions)
        self._records[(card.version_hash, manifest.byte_hash)] = record
        return record

    def is_current(self, card: CapabilityCard, manifest: DisclosureManifest) -> bool:
        try:
            require_valid_card(card)
        except CardValidationError:
            return False
        record = self._records.get((card.version_hash, manifest.byte_hash))
        return bool(record and not record.withdrawn and manifest.verify_card(card))

    def require(self, card: CapabilityCard, manifest: DisclosureManifest) -> ConsentRecord:
        if not self.is_current(card, manifest):
            raise ConsentError(
                "fresh consent is required for this immutable Card version and disclosure manifest"
            )
        return self._records[(card.version_hash, manifest.byte_hash)]

    def withdraw(self, card: CapabilityCard, manifest: DisclosureManifest) -> None:
        key = (card.version_hash, manifest.byte_hash)
        record = self._records.get(key)
        if record is None:
            return
        self._records[key] = record.model_copy(
            update={"withdrawn": True, "permissions": record.permissions.withdraw_all()}
        )


VersionConsent = ConsentRecord
