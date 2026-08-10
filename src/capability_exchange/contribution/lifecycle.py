"""Local contribution lifecycle and withdrawal propagation ports (G4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from capability_exchange.cards.disclosure import DisclosureManifest
from capability_exchange.cards.model import CapabilityCard
from capability_exchange.contribution.consent import ConsentLedger, PermissionSet
from capability_exchange.contribution.provenance import VersionProvenance, build_provenance

__all__ = [
    "Contribution",
    "ContributionLifecycle",
    "ContributionState",
    "IllegalTransition",
    "PermissionDenied",
    "InMemoryStore",
    "StorePort",
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

    def put(self, version_hash: str, payload: bytes) -> None: ...

    def withdraw(self, version_hash: str) -> None: ...

    def quarantine(self, version_hash: str) -> None: ...


@dataclass(slots=True)
class InMemoryStore:
    """Synthetic controlled store used by tests and local lifecycle adapters."""

    name: str
    fail_withdraw: bool = False
    payloads: dict[str, bytes] = field(default_factory=dict)
    withdrawn_versions: set[str] = field(default_factory=set)
    quarantined_versions: set[str] = field(default_factory=set)

    def put(self, version_hash: str, payload: bytes) -> None:
        if version_hash not in self.withdrawn_versions:
            self.payloads[version_hash] = bytes(payload)

    def withdraw(self, version_hash: str) -> None:
        if self.fail_withdraw:
            raise RuntimeError(f"{self.name} withdrawal propagation failed")
        self.payloads.pop(version_hash, None)
        self.withdrawn_versions.add(version_hash)

    def quarantine(self, version_hash: str) -> None:
        self.payloads.pop(version_hash, None)
        self.quarantined_versions.add(version_hash)

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
            ContributionState.ELIGIBLE,
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

    def __init__(self, *, stores: list[StorePort], consent: ConsentLedger) -> None:
        self.stores = tuple(stores)
        self.consent = consent

    def draft(
        self,
        card: CapabilityCard,
        manifest: DisclosureManifest,
        *,
        contributor_secret: bytes,
    ) -> Contribution:
        record = self.consent.require(card, manifest)
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

    def submit(self, contribution: Contribution) -> Contribution:
        if contribution.permissions.is_unresolvable or contribution.permissions.review is not True:
            # Unknown permission state is not a prompt to ask for more access;
            # it is fully withdrawn and cannot reach review.
            self._transition(contribution, ContributionState.WITHDRAWN)
            contribution.withdrawal_reason = (
                "permission state was unresolvable"
                if contribution.permissions.is_unresolvable
                else "review permission was not granted"
            )
            self._propagate_withdrawal(contribution)
            return contribution
        self._transition(contribution, ContributionState.SUBMITTED)
        for store in self.stores:
            if contribution.permissions.storage is True:
                store.put(contribution.version_hash, contribution.manifest.payload_bytes)
        return contribution

    def quarantine(self, contribution: Contribution, reason: str) -> Contribution:
        self._transition(contribution, ContributionState.QUARANTINED)
        contribution.audit_events.append("quarantine:" + _safe_reason(reason))
        for store in self.stores:
            store.quarantine(contribution.version_hash)
        return contribution

    def mark_reviewed(self, contribution: Contribution) -> Contribution:
        if contribution.permissions.moderation is not True:
            raise PermissionDenied("moderation permission is not granted for this Card version")
        self._transition(contribution, ContributionState.REVIEWED)
        return contribution

    def request_changes(self, contribution: Contribution, reason: str) -> Contribution:
        self._transition(contribution, ContributionState.CHANGES_REQUESTED)
        contribution.audit_events.append("changes:" + _safe_reason(reason))
        return contribution

    def reject(self, contribution: Contribution, reason: str) -> Contribution:
        self._transition(contribution, ContributionState.REJECTED)
        contribution.audit_events.append("rejection:" + _safe_reason(reason))
        return contribution

    def mark_eligible(self, contribution: Contribution) -> Contribution:
        if contribution.permissions.reuse is not True:
            raise PermissionDenied("reuse permission is not granted for this Card version")
        if contribution.permissions.distribution is not True:
            raise PermissionDenied("distribution permission is not granted for this Card version")
        self._transition(contribution, ContributionState.ELIGIBLE)
        return contribution

    def withdraw(self, contribution: Contribution, *, reason: str) -> Contribution:
        if contribution.state is not ContributionState.WITHDRAWN:
            self._transition(contribution, ContributionState.WITHDRAWN)
        contribution.withdrawal_reason = _safe_reason(reason)
        self._propagate_withdrawal(contribution)
        return contribution

    def _propagate_withdrawal(self, contribution: Contribution) -> None:
        for store in self.stores:
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
