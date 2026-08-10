"""AI-led pre-review scanning and separate Dave-final approval (R5/R4)."""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from html import escape
from typing import Protocol, final

from pydantic import ConfigDict

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.cards.model import CapabilityCard
from capability_exchange.cards.validation import ValidationIssue, validate_card
from capability_exchange.contribution.provenance import pseudonymous_contributor_ref

__all__ = [
    "ModerationAttestation",
    "ModerationResult",
    "ModerationService",
    "ModerationStatus",
    "ScannerTimeout",
    "ScannerUnavailable",
    "ModerationPipeline",
    "DaveFinalApprovalPort",
    "ScannerPort",
]


class ModerationStatus(StrEnum):
    SCANNED = "scanner-passed"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    APPROVED = "approved"


class ScannerUnavailable(RuntimeError):
    """The pre-review scanner is down; submission stays quarantined."""


class ScannerTimeout(RuntimeError):
    """The pre-review scanner timed out; submission is rejected fail-closed."""


class ScannerPort(Protocol):
    def __call__(self, card: CapabilityCard) -> tuple[ValidationIssue, ...]: ...


@final
class ModerationResult(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    card_version_hash: str
    status: ModerationStatus
    reason_codes: tuple[str, ...]
    reviewable: bool


@final
class ModerationAttestation(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    card_version_hash: str
    reviewer_id: str
    rights_attested: bool
    conflict_declared: bool
    attestation_id: str


class ModerationService:
    """A small explicit moderation port with no agentic execution path."""

    def __init__(
        self,
        *,
        eligible_reviewers: set[str] | None = None,
        local_secret: bytes = b"m5-scanner",
        scanner: ScannerPort
        | Callable[[CapabilityCard], tuple[ValidationIssue, ...]]
        | None = None,
    ) -> None:
        self.eligible_reviewers = frozenset(eligible_reviewers or {"dave"})
        self._local_secret = local_secret
        self._scanner = scanner
        self.attestations: dict[str, ModerationAttestation] = {}

    def scan(self, card: CapabilityCard) -> ModerationResult:
        try:
            if self._scanner is None:
                issues = validate_card(card)
            elif callable(self._scanner):
                issues = tuple(self._scanner(card))
            else:
                issues = tuple(self._scanner.scan(card))  # type: ignore[attr-defined]
        except (ScannerTimeout, TimeoutError):
            return self.handle_scanner_failure(ScannerTimeout(), card=card)
        except (ScannerUnavailable, ConnectionError):
            return self.handle_scanner_failure(ScannerUnavailable(), card=card)
        except Exception:  # noqa: BLE001 - scanner errors quarantine before review
            return self.handle_scanner_failure(ScannerUnavailable(), card=card)
        if issues:
            codes = tuple(
                dict.fromkeys(
                    getattr(getattr(issue, "reason", issue), "value", str(issue))
                    for issue in issues
                )
            )
            return ModerationResult(
                card_version_hash=card.version_hash,
                status=ModerationStatus.QUARANTINED,
                reason_codes=codes,
                reviewable=False,
            )
        return ModerationResult(
            card_version_hash=card.version_hash,
            status=ModerationStatus.SCANNED,
            reason_codes=(),
            reviewable=True,
        )

    def handle_scanner_failure(
        self, failure: Exception, *, card: CapabilityCard | None = None
    ) -> ModerationResult:
        version_hash = card.version_hash if card is not None else "sha256:" + "0" * 64
        if isinstance(failure, (ScannerTimeout, TimeoutError)):
            return ModerationResult(
                card_version_hash=version_hash,
                status=ModerationStatus.REJECTED,
                reason_codes=("scanner-timeout",),
                reviewable=False,
            )
        return ModerationResult(
            card_version_hash=version_hash,
            status=ModerationStatus.QUARANTINED,
            reason_codes=("scanner-unavailable",),
            reviewable=False,
        )

    def render_inert(self, card: CapabilityCard) -> str:
        """Render text/JSON only; no instruction interpreter or model call."""

        payload = json.dumps(card.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return '<pre data-card-inert="true">' + escape(payload) + "</pre>"

    def contributor_ref(self, card: CapabilityCard) -> str:
        return pseudonymous_contributor_ref(self._local_secret, card.version_hash)

    def is_trusted(self, card: CapabilityCard) -> bool:
        """Trust derives from a stored moderation attestation, never Card text."""

        attestation = self.attestations.get(card.version_hash)
        return bool(
            attestation
            and attestation.card_version_hash == card.version_hash
            and attestation.rights_attested
            and attestation.conflict_declared
        )

    def trust_status(self, card: CapabilityCard) -> str:
        return "reviewed" if self.is_trusted(card) else "untrusted"

    def approve(
        self,
        card: CapabilityCard,
        *,
        reviewer_id: str,
        contributor_ref: str,
        rights_attested: bool,
        conflict_declared: bool = False,
        conflict_of_interest: bool = False,
    ) -> ModerationAttestation:
        if reviewer_id not in self.eligible_reviewers:
            raise ValueError("reviewer is not eligible for this moderation port")
        if not contributor_ref.strip():
            raise ValueError("contributor reference is required for conflict checks")
        if reviewer_id == contributor_ref or contributor_ref == self.contributor_ref(card):
            raise ValueError("conflict: a contributor cannot approve their own Card version")
        if conflict_of_interest:
            raise ValueError("conflict: reviewer declared a conflict of interest")
        if not rights_attested or not card.rights.rights_attested:
            raise ValueError("rights attestation is required before approval")
        if not conflict_declared:
            raise ValueError("conflict declaration is required before approval")
        scanned = self.scan(card)
        if scanned.status is not ModerationStatus.SCANNED:
            raise ValueError("Card is quarantined by the pre-review scanner")
        attestation_id = f"moderation:{card.version_hash}:{reviewer_id}"
        attestation = ModerationAttestation(
            card_version_hash=card.version_hash,
            reviewer_id=reviewer_id,
            rights_attested=True,
            conflict_declared=True,
            attestation_id=attestation_id,
        )
        self.attestations[card.version_hash] = attestation
        return attestation


ModerationPipeline = ModerationService


class DaveFinalApprovalPort:
    """Separate human-final port; scanner decisions cannot self-approve."""

    def __init__(
        self,
        *,
        eligible_reviewers: set[str] | None = None,
        local_secret: bytes = b"m5-scanner",
    ) -> None:
        self._service = ModerationService(
            eligible_reviewers=eligible_reviewers,
            local_secret=local_secret,
        )

    def approve(self, card: CapabilityCard, **kwargs: object) -> ModerationAttestation:
        return self._service.approve(card, **kwargs)  # type: ignore[arg-type]

    def render_inert(self, card: CapabilityCard) -> str:
        return self._service.render_inert(card)

    def is_trusted(self, card: CapabilityCard) -> bool:
        return self._service.is_trusted(card)

    def contributor_ref(self, card: CapabilityCard) -> str:
        return self._service.contributor_ref(card)

    def trust_status(self, card: CapabilityCard) -> str:
        return self._service.trust_status(card)
