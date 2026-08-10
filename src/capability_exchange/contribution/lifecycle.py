"""Local contribution lifecycle and withdrawal propagation ports (G4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from capability_exchange.cards.disclosure import DisclosureManifest
from capability_exchange.cards.model import CapabilityCard
from capability_exchange.cards.validation import CardValidationError, require_valid_card
from capability_exchange.contribution.consent import (
    ConsentError,
    ConsentLedger,
    ConsentRecord,
    PermissionSet,
)
from capability_exchange.contribution.provenance import VersionProvenance, build_provenance

__all__ = [
    "Contribution",
    "ContributionLifecycle",
    "ContributionState",
    "IllegalTransition",
    "PermissionDenied",
    "InMemoryStore",
    "StorePort",
    "ModerationTrustPort",
    "ContributionLifecycleService",
    "SyntheticStore",
]


class ContributionState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted-for-review"
    QUARANTINED = "quarantined"
    REVIEWED = "reviewed"
    CHANGES_REQUESTED = "changes-requested"
    REJECTED = "rejected"
    ELIGIBLE = "eligible-for-core-consideration"
    WITHDRAWN = "withdrawn"

    # Integration-friendly aliases used by callers that shorten the labels.
    SUBMITTED_FOR_REVIEW = "submitted-for-review"
    ELIGIBLE_FOR_CORE = "eligible-for-core-consideration"


class IllegalTransition(ValueError):
    """A lifecycle transition is not valid for the current state."""


class PermissionDenied(ValueError):
    """A separately controlled permission is not granted for this version."""


class StorePort(Protocol):
    name: str
    recallable: bool

    def put(self, version_hash: str, payload: bytes) -> None: ...

    def withdraw(self, version_hash: str) -> None: ...

    def quarantine(self, version_hash: str) -> None: ...

    def mark_non_recallable(self, version_hash: str) -> None: ...


class ModerationTrustPort(Protocol):
    """Read-only trust seam for immutable, signed moderation attestations."""

    def attestation_for(self, card: CapabilityCard) -> object | None: ...

    def verify_attestation(self, card: CapabilityCard, attestation: object) -> bool: ...


@dataclass(slots=True)
class InMemoryStore:
    """Synthetic controlled store used by tests and local lifecycle adapters."""

    name: str
    fail_withdraw: bool = False
    recallable: bool | None = None
    payloads: dict[str, bytes] = field(default_factory=dict)
    withdrawn_versions: set[str] = field(default_factory=set)
    quarantined_versions: set[str] = field(default_factory=set)
    non_recallable_versions: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        # A shipped Core release is outside Exchange control.  Keep its bytes
        # and record the honest non-recallable boundary on withdrawal.
        if self.name == "core-release":
            if self.recallable is True:
                raise ValueError("core-release stores are permanently non-recallable")
            self.recallable = False
        elif self.recallable is None:
            self.recallable = True

    def put(self, version_hash: str, payload: bytes) -> None:
        if version_hash not in self.withdrawn_versions:
            self.payloads[version_hash] = bytes(payload)

    def withdraw(self, version_hash: str) -> None:
        if self.fail_withdraw:
            raise RuntimeError(f"{self.name} withdrawal propagation failed")
        if self.recallable is False:
            self.mark_non_recallable(version_hash)
            return
        self.payloads.pop(version_hash, None)
        self.withdrawn_versions.add(version_hash)

    def quarantine(self, version_hash: str) -> None:
        self.payloads.pop(version_hash, None)
        self.quarantined_versions.add(version_hash)

    def mark_non_recallable(self, version_hash: str) -> None:
        self.non_recallable_versions.add(version_hash)

    def can_use(self, version_hash: str) -> bool:
        return (
            version_hash in self.payloads
            and version_hash not in self.withdrawn_versions | self.quarantined_versions
        )


@dataclass(slots=True)
class Contribution:
    """Mutable local lifecycle envelope around an immutable Card version."""

    card: CapabilityCard
    manifest: DisclosureManifest
    permissions: PermissionSet
    provenance: VersionProvenance
    state: ContributionState = ContributionState.DRAFT
    audit_events: list[str] = field(default_factory=list)
    withdrawal_reason: str | None = None

    @property
    def version_hash(self) -> str:
        return self.card.version_hash

    @property
    def withdrawal_disclosure(self) -> str:
        return (
            "Withdrawal stops new review, reuse, attribution, and distribution where feasible. "
            "A shipped Core release cannot be recalled; that limit is disclosed before any "
            "separate Core-adoption agreement."
        )


_ALLOWED: dict[ContributionState, frozenset[ContributionState]] = {
    ContributionState.DRAFT: frozenset({ContributionState.SUBMITTED, ContributionState.WITHDRAWN}),
    ContributionState.SUBMITTED: frozenset(
        {
            ContributionState.QUARANTINED,
            ContributionState.REVIEWED,
            ContributionState.CHANGES_REQUESTED,
            ContributionState.REJECTED,
            ContributionState.WITHDRAWN,
        }
    ),
    ContributionState.QUARANTINED: frozenset(
        {
            ContributionState.SUBMITTED,
            ContributionState.REJECTED,
            ContributionState.WITHDRAWN,
        }
    ),
    ContributionState.REVIEWED: frozenset(
        {ContributionState.ELIGIBLE, ContributionState.WITHDRAWN}
    ),
    ContributionState.CHANGES_REQUESTED: frozenset({ContributionState.WITHDRAWN}),
    ContributionState.REJECTED: frozenset({ContributionState.WITHDRAWN}),
    ContributionState.ELIGIBLE: frozenset({ContributionState.WITHDRAWN}),
    ContributionState.WITHDRAWN: frozenset(),
}


class ContributionLifecycle:
    """State machine coordinating consent and synthetic controlled stores."""

    def __init__(
        self,
        *,
        stores: list[StorePort],
        consent: ConsentLedger,
        moderation: ModerationTrustPort | None = None,
        moderation_service: ModerationTrustPort | None = None,
    ) -> None:
        if moderation is not None and moderation_service is not None:
            raise ValueError("provide only one moderation trust port")
        self.stores = tuple(stores)
        self.consent = consent
        self._moderation = moderation if moderation is not None else moderation_service

    @property
    def moderation(self) -> ModerationTrustPort | None:
        """Read-only moderation trust dependency."""

        return self._moderation

    def draft(
        self,
        card: CapabilityCard,
        manifest: DisclosureManifest,
        *,
        contributor_secret: bytes,
    ) -> Contribution:
        try:
            require_valid_card(card)
            record = self.consent.require(card, manifest)
        except CardValidationError as exc:
            raise CardValidationError(exc.issues) from exc
        except ConsentError:
            raise
        provenance = build_provenance(
            local_secret=contributor_secret,
            card_version_hash=card.version_hash,
            method_basis=card.provenance.method_basis,
            evidence_basis=card.provenance.evidence_basis,
            adapter_id=card.provenance.adapter_id,
            evidence_mode=card.provenance.evidence_mode,
            approved_fields=manifest.approved_fields,
        )
        return Contribution(
            card=card,
            manifest=manifest,
            permissions=record.permissions,
            provenance=provenance,
            audit_events=["draft-created"],
        )

    def _transition(self, contribution: Contribution, target: ContributionState) -> None:
        if target not in _ALLOWED[contribution.state]:
            raise IllegalTransition(
                f"cannot transition contribution from {contribution.state.value} to {target.value}"
            )
        contribution.state = target
        contribution.audit_events.append(target.value)

    def _assert_transition(self, contribution: Contribution, target: ContributionState) -> None:
        if target not in _ALLOWED[contribution.state]:
            raise IllegalTransition(
                f"cannot transition contribution from {contribution.state.value} to {target.value}"
            )

    def _require_active_consent(self, contribution: Contribution) -> ConsentRecord:
        if contribution.state is ContributionState.WITHDRAWN:
            raise IllegalTransition("withdrawn Card versions cannot be used again")
        try:
            require_valid_card(contribution.card)
            record = self.consent.require(contribution.card, contribution.manifest)
        except CardValidationError as exc:
            self._revoke_and_withdraw(contribution, "Card validation failed")
            raise CardValidationError(exc.issues) from exc
        except ConsentError as exc:
            self._revoke_and_withdraw(contribution, "consent was withdrawn")
            raise ConsentError(
                "withdrawn Card versions cannot be redrafted or resubmitted"
            ) from exc
        return record

    def _require_moderation_attestation(self, contribution: Contribution) -> None:
        if self._moderation is None:
            raise PermissionDenied("immutable moderation attestation is required before review")
        try:
            attestation = self._moderation.attestation_for(contribution.card)
            trusted = attestation is not None and self._moderation.verify_attestation(
                contribution.card, attestation
            )
        except Exception:  # noqa: BLE001 - trust ports fail closed
            trusted = False
        if not trusted:
            raise PermissionDenied(
                "scanner pass and a verifier-approved moderation attestation are required"
            )

    def submit(self, contribution: Contribution) -> Contribution:
        record = self._require_active_consent(contribution)
        permissions = record.permissions
        if permissions.is_unresolvable or permissions.review is not True:
            # Unknown permission state is not a prompt to ask for more access;
            # it is fully withdrawn and cannot reach review.
            reason = (
                "permission state was unresolvable"
                if permissions.is_unresolvable
                else "review permission was not granted"
            )
            self._revoke_and_withdraw(contribution, reason)
            return contribution
        # Consent may be valid while a caller hands us a forged manifest or a
        # Card changed through a bypass route.  Re-check before any store.put.
        outbound = self.consent.authorize_outbound(contribution.card, contribution.manifest)
        self._transition(contribution, ContributionState.SUBMITTED)
        for store in self.stores:
            if permissions.storage is True:
                store.put(contribution.version_hash, outbound)
        return contribution

    def quarantine(self, contribution: Contribution, reason: str) -> Contribution:
        self._require_active_consent(contribution)
        self._transition(contribution, ContributionState.QUARANTINED)
        contribution.audit_events.append("quarantine:" + _safe_reason(reason))
        for store in self.stores:
            store.quarantine(contribution.version_hash)
        return contribution

    def mark_reviewed(self, contribution: Contribution) -> Contribution:
        self._assert_transition(contribution, ContributionState.REVIEWED)
        record = self._require_active_consent(contribution)
        if record.permissions.moderation is not True:
            raise PermissionDenied("moderation permission is not granted for this Card version")
        self._require_moderation_attestation(contribution)
        self._transition(contribution, ContributionState.REVIEWED)
        return contribution

    def request_changes(self, contribution: Contribution, reason: str) -> Contribution:
        self._assert_transition(contribution, ContributionState.CHANGES_REQUESTED)
        self._require_active_consent(contribution)
        self._require_moderation_attestation(contribution)
        self._transition(contribution, ContributionState.CHANGES_REQUESTED)
        contribution.audit_events.append("changes:" + _safe_reason(reason))
        return contribution

    def reject(self, contribution: Contribution, reason: str) -> Contribution:
        self._assert_transition(contribution, ContributionState.REJECTED)
        self._require_active_consent(contribution)
        self._require_moderation_attestation(contribution)
        self._transition(contribution, ContributionState.REJECTED)
        contribution.audit_events.append("rejection:" + _safe_reason(reason))
        return contribution

    def mark_eligible(self, contribution: Contribution) -> Contribution:
        self._assert_transition(contribution, ContributionState.ELIGIBLE)
        record = self._require_active_consent(contribution)
        self._require_moderation_attestation(contribution)
        if record.permissions.reuse is not True:
            raise PermissionDenied("reuse permission is not granted for this Card version")
        if record.permissions.distribution is not True:
            raise PermissionDenied("distribution permission is not granted for this Card version")
        self._transition(contribution, ContributionState.ELIGIBLE)
        return contribution

    def withdraw(self, contribution: Contribution, *, reason: str) -> Contribution:
        if contribution.state is ContributionState.WITHDRAWN:
            raise IllegalTransition("contribution is already withdrawn")
        self.consent.withdraw(contribution.card, contribution.manifest)
        if contribution.state is not ContributionState.WITHDRAWN:
            self._transition(contribution, ContributionState.WITHDRAWN)
        contribution.withdrawal_reason = _safe_reason(reason)
        contribution.permissions = contribution.permissions.withdraw_all()
        self._propagate_withdrawal(contribution)
        return contribution

    def _revoke_and_withdraw(self, contribution: Contribution, reason: str) -> None:
        self.consent.withdraw(contribution.card, contribution.manifest)
        if contribution.state is not ContributionState.WITHDRAWN:
            self._transition(contribution, ContributionState.WITHDRAWN)
        contribution.withdrawal_reason = _safe_reason(reason)
        contribution.permissions = contribution.permissions.withdraw_all()
        self._propagate_withdrawal(contribution)

    def _propagate_withdrawal(self, contribution: Contribution) -> None:
        for store in self.stores:
            if getattr(store, "recallable", True) is False:
                marker = getattr(store, "mark_non_recallable", None)
                if callable(marker):
                    marker(contribution.version_hash)
                contribution.audit_events.append("withdrawal-non-recallable:" + store.name)
                continue
            try:
                store.withdraw(contribution.version_hash)
            except Exception:  # noqa: BLE001 - a failed controlled port quarantines its copy
                store.quarantine(contribution.version_hash)
                contribution.audit_events.append("withdrawal-quarantined:" + store.name)
            else:
                contribution.audit_events.append("withdrawal-propagated:" + store.name)


def _safe_reason(reason: str) -> str:
    """Audit only a bounded reason; never retain arbitrary source material."""

    cleaned = " ".join(str(reason).split())
    return cleaned[:240] or "unspecified"


ContributionLifecycleService = ContributionLifecycle
SyntheticStore = InMemoryStore
