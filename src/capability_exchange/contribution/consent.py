"""Per-version contribution consent and six-permission lifecycle (G4)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import final

from pydantic import ConfigDict, StrictBool, ValidationError

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

    review: StrictBool | None
    storage: StrictBool | None
    moderation: StrictBool | None
    attribution: StrictBool | None
    reuse: StrictBool | None
    distribution: StrictBool | None

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
    withdrawn: StrictBool = False

    @classmethod
    def now(
        cls,
        card: CapabilityCard,
        manifest: DisclosureManifest,
        permissions: PermissionSet,
    ) -> ConsentRecord:
        card = require_valid_card(card)
        if not manifest.verify_card(card):
            raise ConsentError("disclosure manifest does not match this Card version")
        permissions = PermissionSet.model_validate(dict(permissions.__dict__))
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
        self._withdrawn_versions: set[str] = set()

    def grant(
        self,
        card: CapabilityCard,
        manifest: DisclosureManifest,
        permissions: PermissionSet,
    ) -> ConsentRecord:
        try:
            card = require_valid_card(card)
        except CardValidationError as exc:
            raise ConsentError(
                "Card validation failed before consent: " + ", ".join(exc.reason_codes)
            ) from exc
        if card.version_hash in self._withdrawn_versions:
            raise ConsentError("this immutable Card version was withdrawn and cannot be re-granted")
        if any(version_hash == card.version_hash for version_hash, _ in self._records):
            raise ConsentError("consent for this immutable Card version is already recorded")
        if not manifest.verify_card(card):
            raise ConsentError("disclosure manifest does not match this Card version")
        if card.rights.rights_attested is not True:
            raise ConsentError("rights attestation is required before version consent")
        try:
            permissions = PermissionSet.model_validate(dict(permissions.__dict__))
        except (AttributeError, ValidationError) as exc:
            raise ConsentError("permission grant failed exact validation") from exc
        undeclared = tuple(
            permission.value
            for permission in Permission
            if getattr(permissions, permission.value) is True
            and getattr(card.permissions, permission.value) is not True
        )
        if undeclared:
            raise ConsentError(
                "consent permissions exceed those declared by the Card: "
                + ", ".join(undeclared)
            )
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

    def authorize_outbound(
        self, card: CapabilityCard, manifest: DisclosureManifest
    ) -> bytes:
        """Return only the exact bytes covered by active version consent.

        The ledger, rather than a caller-supplied boolean, is the sole local
        authorization seam. Both Card and manifest are rebuilt through their
        validators so Pydantic's construction escape hatches cannot cross it.
        """

        try:
            validated_card = require_valid_card(card)
            self.require(validated_card, manifest)
            if not manifest.verify_card(validated_card):
                raise ConsentError("disclosure manifest does not match this Card version")
            # Rebuild the expected manifest from the validated Card; return its
            # bytes, not bytes held by the caller's object.
            from capability_exchange.cards.disclosure import build_disclosure_manifest

            expected = build_disclosure_manifest(
                validated_card, approved_fields=manifest.approved_fields
            )
        except (CardValidationError, ValueError, TypeError) as exc:
            raise ConsentError("disclosure manifest failed revalidation") from exc
        if (
            expected.byte_hash != manifest.byte_hash
            or expected.display_text != manifest.display_text
        ):
            raise ConsentError("disclosure manifest does not match this Card version")
        return expected.payload_bytes

    def withdraw(self, card: CapabilityCard, manifest: DisclosureManifest) -> None:
        self._withdrawn_versions.add(card.version_hash)
        key = (card.version_hash, manifest.byte_hash)
        record = self._records.get(key)
        if record is None:
            return
        self._records[key] = record.model_copy(
            update={"withdrawn": True, "permissions": record.permissions.withdraw_all()}
        )


VersionConsent = ConsentRecord
