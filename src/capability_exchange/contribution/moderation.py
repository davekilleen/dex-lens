"""AI-led pre-review scanning and separate Dave-final approval (R5/R4)."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from enum import StrEnum
from html import escape
from types import MappingProxyType
from typing import Protocol, final

from pydantic import ConfigDict, field_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.cards.model import CapabilityCard
from capability_exchange.cards.validation import (
    CardValidationError,
    ValidationIssue,
    require_valid_card,
    validate_card,
)
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
    "AttestationSigner",
    "AttestationVerifier",
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


class AttestationSigner(Protocol):
    """Port that issues an immutable moderation-attestation signature."""

    def sign(self, payload: bytes, key_id: str) -> str: ...


class AttestationVerifier(Protocol):
    """Port that decides whether a moderation signature is trusted."""

    def verify(self, payload: bytes, signature: str, key_id: str) -> bool: ...


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
    scanner_passed: bool
    signature: str
    key_id: str
    attestation_id: str

    @field_validator("card_version_hash", "reviewer_id", "signature", "key_id", "attestation_id")
    @classmethod
    def _bounded_identity(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise ValueError("moderation attestation identifiers must be bounded and non-empty")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("moderation attestation identifiers cannot contain controls")
        return value


class _HmacAttestationTrust:
    """Small local default trust port; production injects a real signer."""

    def __init__(self, secret: bytes) -> None:
        self._secret = bytes(secret)

    def sign(self, payload: bytes, key_id: str) -> str:
        digest = hmac.new(self._secret, key_id.encode("utf-8") + b"\0" + payload, hashlib.sha256)
        return "hmac-sha256:" + digest.hexdigest()

    def verify(self, payload: bytes, signature: str, key_id: str) -> bool:
        expected = self.sign(payload, key_id)
        return hmac.compare_digest(expected, signature)


def _attestation_payload(
    *,
    card_version_hash: str,
    reviewer_id: str,
    rights_attested: bool,
    conflict_declared: bool,
    scanner_passed: bool,
    key_id: str,
) -> bytes:
    return json.dumps(
        {
            "card_version_hash": card_version_hash,
            "reviewer_id": reviewer_id,
            "rights_attested": rights_attested,
            "conflict_declared": conflict_declared,
            "scanner_passed": scanner_passed,
            "key_id": key_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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
        signer: AttestationSigner | Callable[[bytes, str], str] | None = None,
        verifier: AttestationVerifier
        | Callable[[bytes, str, str], bool]
        | None = None,
        attestation_key_id: str = "moderation-1",
    ) -> None:
        self.eligible_reviewers = frozenset(eligible_reviewers or {"dave"})
        self._local_secret = local_secret
        self._scanner = scanner
        default_trust = _HmacAttestationTrust(local_secret)
        self._signer = signer or default_trust
        self._verifier = verifier or default_trust
        self._attestation_key_id = attestation_key_id
        self._attestations: dict[str, ModerationAttestation] = {}

    @property
    def attestations(self) -> Mapping[str, ModerationAttestation]:
        """Read-only view; callers cannot insert caller-asserted trust."""

        return MappingProxyType(self._attestations)

    def scan(self, card: CapabilityCard) -> ModerationResult:
        try:
            require_valid_card(card)
            if self._scanner is None:
                issues = validate_card(card)
            elif callable(self._scanner):
                issues = tuple(self._scanner(card))
            else:
                issues = tuple(self._scanner.scan(card))  # type: ignore[attr-defined]
        except CardValidationError as failure:
            return ModerationResult(
                card_version_hash=card.version_hash,
                status=ModerationStatus.QUARANTINED,
                reason_codes=failure.reason_codes,
                reviewable=False,
            )
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

        require_valid_card(card)
        payload = json.dumps(card.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return '<pre data-card-inert="true">' + escape(payload) + "</pre>"

    def contributor_ref(self, card: CapabilityCard) -> str:
        return pseudonymous_contributor_ref(self._local_secret, card.version_hash)

    def is_trusted(self, card: CapabilityCard) -> bool:
        """Trust derives from a private, signed attestation and verifier port."""

        try:
            require_valid_card(card)
        except CardValidationError:
            return False
        attestation = self._attestations.get(card.version_hash)
        return attestation is not None and self.verify_attestation(card, attestation)

    def attestation_for(self, card: CapabilityCard) -> ModerationAttestation | None:
        """Return the immutable attestation without exposing the backing store."""

        return self._attestations.get(card.version_hash)

    def verify_attestation(
        self, card: CapabilityCard, attestation: ModerationAttestation
    ) -> bool:
        """Verify version, reviewer, scanner, rights, conflict, and signature."""

        try:
            require_valid_card(card)
            if attestation.card_version_hash != card.version_hash:
                return False
            if attestation.reviewer_id not in self.eligible_reviewers:
                return False
            if not (
                attestation.scanner_passed
                and attestation.rights_attested
                and attestation.conflict_declared
            ):
                return False
            payload = _attestation_payload(
                card_version_hash=attestation.card_version_hash,
                reviewer_id=attestation.reviewer_id,
                rights_attested=attestation.rights_attested,
                conflict_declared=attestation.conflict_declared,
                scanner_passed=attestation.scanner_passed,
                key_id=attestation.key_id,
            )
            if callable(self._verifier):
                return bool(
                    self._verifier(payload, attestation.signature, attestation.key_id)
                )
            return bool(
                self._verifier.verify(payload, attestation.signature, attestation.key_id)
            )
        except Exception:  # noqa: BLE001 - trust failures fail closed
            return False

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
        key_id = self._attestation_key_id
        payload = _attestation_payload(
            card_version_hash=card.version_hash,
            reviewer_id=reviewer_id,
            rights_attested=True,
            conflict_declared=True,
            scanner_passed=True,
            key_id=key_id,
        )
        if callable(self._signer):
            signature = self._signer(payload, key_id)
        else:
            signature = self._signer.sign(payload, key_id)
        digest = hashlib.sha256(payload).hexdigest()
        attestation_id = f"moderation:{card.version_hash}:{reviewer_id}:{digest}"
        attestation = ModerationAttestation(
            card_version_hash=card.version_hash,
            reviewer_id=reviewer_id,
            rights_attested=True,
            conflict_declared=True,
            scanner_passed=True,
            signature=signature,
            key_id=key_id,
            attestation_id=attestation_id,
        )
        if not self.verify_attestation(card, attestation):
            raise ValueError("moderation attestation signature failed verification")
        self._attestations[card.version_hash] = attestation
        return attestation


ModerationPipeline = ModerationService


class DaveFinalApprovalPort:
    """Separate human-final port; scanner decisions cannot self-approve."""

    def __init__(
        self,
        *,
        eligible_reviewers: set[str] | None = None,
        local_secret: bytes = b"m5-scanner",
        signer: AttestationSigner | Callable[[bytes, str], str] | None = None,
        verifier: AttestationVerifier
        | Callable[[bytes, str, str], bool]
        | None = None,
        attestation_key_id: str = "moderation-1",
    ) -> None:
        self._service = ModerationService(
            eligible_reviewers=eligible_reviewers,
            local_secret=local_secret,
            signer=signer,
            verifier=verifier,
            attestation_key_id=attestation_key_id,
        )

    def approve(self, card: CapabilityCard, **kwargs: object) -> ModerationAttestation:
        return self._service.approve(card, **kwargs)  # type: ignore[arg-type]

    def render_inert(self, card: CapabilityCard) -> str:
        return self._service.render_inert(card)

    def is_trusted(self, card: CapabilityCard) -> bool:
        return self._service.is_trusted(card)

    def verify_attestation(
        self, card: CapabilityCard, attestation: ModerationAttestation
    ) -> bool:
        return self._service.verify_attestation(card, attestation)

    def contributor_ref(self, card: CapabilityCard) -> str:
        return self._service.contributor_ref(card)

    def trust_status(self, card: CapabilityCard) -> str:
        return self._service.trust_status(card)
