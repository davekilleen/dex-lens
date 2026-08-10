"""AI-led pre-review scanning and separate Dave-final approval (R5/R4)."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from enum import StrEnum
from html import escape
from types import MappingProxyType
from typing import Protocol, final

from pydantic import ConfigDict, StrictBool, field_validator

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
    "PrincipalIdentityPort",
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


class PrincipalIdentityPort(Protocol):
    """Trusted authentication seam; request callers never supply identities."""

    def authenticated_principal(self) -> str: ...


@final
class ModerationResult(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    card_version_hash: str
    status: ModerationStatus
    reason_codes: tuple[str, ...]
    reviewable: StrictBool


@final
class ModerationAttestation(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    card_version_hash: str
    reviewer_id: str
    contributor_id: str
    rights_attested: StrictBool
    conflict_declared: StrictBool
    scanner_passed: StrictBool
    scanner_id: str
    scanner_version: str
    scanner_reason_codes: tuple[str, ...]
    scanner_result_hash: str
    signature: str
    key_id: str
    attestation_id: str

    @field_validator(
        "card_version_hash",
        "reviewer_id",
        "contributor_id",
        "scanner_id",
        "scanner_version",
        "scanner_result_hash",
        "signature",
        "key_id",
        "attestation_id",
    )
    @classmethod
    def _bounded_identity(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise ValueError("moderation attestation identifiers must be bounded and non-empty")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("moderation attestation identifiers cannot contain controls")
        return value

    @field_validator("scanner_reason_codes")
    @classmethod
    def _bounded_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        result = tuple(value)
        if len(result) > 64 or any(not item.strip() or len(item) > 128 for item in result):
            raise ValueError("scanner reason codes must be bounded non-empty identifiers")
        return result


def _attestation_payload(
    *,
    card_version_hash: str,
    reviewer_id: str,
    contributor_id: str,
    rights_attested: bool,
    conflict_declared: bool,
    scanner_passed: bool,
    scanner_id: str,
    scanner_version: str,
    scanner_reason_codes: tuple[str, ...],
    scanner_result_hash: str,
    key_id: str,
) -> bytes:
    return json.dumps(
        {
            "card_version_hash": card_version_hash,
            "reviewer_id": reviewer_id,
            "contributor_id": contributor_id,
            "rights_attested": rights_attested,
            "conflict_declared": conflict_declared,
            "scanner_passed": scanner_passed,
            "scanner_id": scanner_id,
            "scanner_version": scanner_version,
            "scanner_reason_codes": scanner_reason_codes,
            "scanner_result_hash": scanner_result_hash,
            "key_id": key_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _scanner_result_hash(
    result: ModerationResult, *, scanner_id: str, scanner_version: str
) -> str:
    payload = json.dumps(
        {
            "result": result.model_dump(mode="json"),
            "scanner_id": scanner_id,
            "scanner_version": scanner_version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class ModerationService:
    """A small explicit moderation port with no agentic execution path."""

    def __init__(
        self,
        *,
        eligible_reviewers: set[str] | None = None,
        local_secret: bytes | None = None,
        scanner: ScannerPort
        | Callable[[CapabilityCard], tuple[ValidationIssue, ...]]
        | None = None,
        signer: AttestationSigner | Callable[[bytes, str], str] | None = None,
        verifier: AttestationVerifier
        | Callable[[bytes, str, str], bool]
        | None = None,
        reviewer_identity: PrincipalIdentityPort | None = None,
        contributor_identity: PrincipalIdentityPort | None = None,
        attestation_key_id: str = "moderation-1",
        trusted_scanners: set[tuple[str, str]] | None = None,
        trusted_key_ids: set[str] | None = None,
    ) -> None:
        self.eligible_reviewers = frozenset(
            set() if eligible_reviewers is None else eligible_reviewers
        )
        self._local_secret = (
            secrets.token_bytes(32) if local_secret is None else bytes(local_secret)
        )
        if not self._local_secret:
            raise ValueError("local moderation secret must be non-empty")
        self._scanner = scanner
        self._signer = signer
        self._verifier = verifier
        self._reviewer_identity = reviewer_identity
        self._contributor_identity = contributor_identity
        self._attestation_key_id = attestation_key_id
        self._trusted_key_ids = frozenset(
            set() if trusted_key_ids is None else trusted_key_ids
        )
        self._scanner_id = (
            "capability-card-validator"
            if scanner is None
            else str(getattr(scanner, "scanner_id", ""))
        )
        self._scanner_version = (
            "1" if scanner is None else str(getattr(scanner, "scanner_version", ""))
        )
        self._trusted_scanners = frozenset(
            {("capability-card-validator", "1")}
            if trusted_scanners is None
            else trusted_scanners
        )
        self._attestations: dict[str, ModerationAttestation] = {}

    @property
    def attestations(self) -> Mapping[str, ModerationAttestation]:
        """Read-only view; callers cannot insert caller-asserted trust."""

        return MappingProxyType(self._attestations)

    def scan(self, card: CapabilityCard) -> ModerationResult:
        try:
            require_valid_card(card)
            if not self._scanner_id.strip() or not self._scanner_version.strip():
                raise ScannerUnavailable("scanner identity/version is not declared")
            if (self._scanner_id, self._scanner_version) not in self._trusted_scanners:
                raise ScannerUnavailable("scanner identity/version is not allowlisted")
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
            if attestation.key_id != self._attestation_key_id:
                return False
            if attestation.key_id not in self._trusted_key_ids or self._verifier is None:
                return False
            if attestation.reviewer_id not in self.eligible_reviewers:
                return False
            if self._contributor_identity is None:
                return False
            contributor_id = self._contributor_identity.authenticated_principal()
            if (
                not isinstance(contributor_id, str)
                or attestation.contributor_id != contributor_id
                or attestation.reviewer_id == attestation.contributor_id
            ):
                return False
            if not (
                attestation.scanner_passed
                and attestation.rights_attested
                and attestation.conflict_declared
            ):
                return False
            current_scan = self.scan(card)
            current_hash = _scanner_result_hash(
                current_scan,
                scanner_id=self._scanner_id,
                scanner_version=self._scanner_version,
            )
            if current_scan.status is not ModerationStatus.SCANNED:
                return False
            if (
                attestation.scanner_id != self._scanner_id
                or attestation.scanner_version != self._scanner_version
                or attestation.scanner_reason_codes != current_scan.reason_codes
                or attestation.scanner_result_hash != current_hash
            ):
                return False
            payload = _attestation_payload(
                card_version_hash=attestation.card_version_hash,
                reviewer_id=attestation.reviewer_id,
                contributor_id=attestation.contributor_id,
                rights_attested=attestation.rights_attested,
                conflict_declared=attestation.conflict_declared,
                scanner_passed=attestation.scanner_passed,
                scanner_id=attestation.scanner_id,
                scanner_version=attestation.scanner_version,
                scanner_reason_codes=attestation.scanner_reason_codes,
                scanner_result_hash=attestation.scanner_result_hash,
                key_id=attestation.key_id,
            )
            if callable(self._verifier):
                verified = self._verifier(
                    payload, attestation.signature, attestation.key_id
                )
            else:
                verified = self._verifier.verify(
                    payload, attestation.signature, attestation.key_id
                )
            return verified is True
        except Exception:  # noqa: BLE001 - trust failures fail closed
            return False

    def trust_status(self, card: CapabilityCard) -> str:
        return "reviewed" if self.is_trusted(card) else "untrusted"

    def approve(
        self,
        card: CapabilityCard,
        *,
        rights_attested: bool,
        conflict_declared: bool = False,
        conflict_of_interest: bool = False,
    ) -> ModerationAttestation:
        if (
            not self.eligible_reviewers
            or self._reviewer_identity is None
            or self._contributor_identity is None
            or self._signer is None
            or self._verifier is None
        ):
            raise ValueError("authenticated reviewer authority is unavailable")
        if self._attestation_key_id not in self._trusted_key_ids:
            raise ValueError("moderation attestation trust root is not pinned")
        reviewer_id = self._reviewer_identity.authenticated_principal()
        contributor_id = self._contributor_identity.authenticated_principal()
        if not isinstance(reviewer_id, str) or not reviewer_id.strip():
            raise ValueError("authenticated reviewer authority returned no principal")
        if not isinstance(contributor_id, str) or not contributor_id.strip():
            raise ValueError("authenticated contributor authority returned no principal")
        if reviewer_id not in self.eligible_reviewers:
            raise ValueError("reviewer is not eligible for this moderation port")
        if reviewer_id == contributor_id:
            raise ValueError("conflict: a contributor cannot approve their own Card version")
        if type(conflict_of_interest) is not bool or conflict_of_interest is True:
            raise ValueError("conflict: reviewer declared a conflict of interest")
        if type(rights_attested) is not bool or rights_attested is not True:
            raise ValueError("rights attestation is required before approval")
        if card.rights.rights_attested is not True:
            raise ValueError("rights attestation is required before approval")
        if type(conflict_declared) is not bool or conflict_declared is not True:
            raise ValueError("conflict declaration is required before approval")
        scanned = self.scan(card)
        if scanned.status is not ModerationStatus.SCANNED:
            raise ValueError("Card is quarantined by the pre-review scanner")
        scanner_hash = _scanner_result_hash(
            scanned,
            scanner_id=self._scanner_id,
            scanner_version=self._scanner_version,
        )
        key_id = self._attestation_key_id
        payload = _attestation_payload(
            card_version_hash=card.version_hash,
            reviewer_id=reviewer_id,
            contributor_id=contributor_id,
            rights_attested=True,
            conflict_declared=True,
            scanner_passed=True,
            scanner_id=self._scanner_id,
            scanner_version=self._scanner_version,
            scanner_reason_codes=scanned.reason_codes,
            scanner_result_hash=scanner_hash,
            key_id=key_id,
        )
        if callable(self._signer):
            signature = self._signer(payload, key_id)
        else:
            signature = self._signer.sign(payload, key_id)
        if not isinstance(signature, str) or not signature:
            raise ValueError("moderation signing authority returned no signature")
        digest = hashlib.sha256(payload).hexdigest()
        attestation_id = f"moderation:{card.version_hash}:{reviewer_id}:{digest}"
        attestation = ModerationAttestation(
            card_version_hash=card.version_hash,
            reviewer_id=reviewer_id,
            contributor_id=contributor_id,
            rights_attested=True,
            conflict_declared=True,
            scanner_passed=True,
            scanner_id=self._scanner_id,
            scanner_version=self._scanner_version,
            scanner_reason_codes=scanned.reason_codes,
            scanner_result_hash=scanner_hash,
            signature=signature,
            key_id=key_id,
            attestation_id=attestation_id,
        )
        if not self.verify_attestation(card, attestation):
            raise ValueError("moderation attestation signature failed verification")
        if card.version_hash in self._attestations:
            raise ValueError("this Card version already has an immutable moderation attestation")
        self._attestations[card.version_hash] = attestation
        return attestation


ModerationPipeline = ModerationService


class DaveFinalApprovalPort:
    """Separate human-final port; scanner decisions cannot self-approve."""

    def __init__(
        self,
        *,
        eligible_reviewers: set[str] | None = None,
        local_secret: bytes | None = None,
        signer: AttestationSigner | Callable[[bytes, str], str] | None = None,
        verifier: AttestationVerifier
        | Callable[[bytes, str, str], bool]
        | None = None,
        reviewer_identity: PrincipalIdentityPort | None = None,
        contributor_identity: PrincipalIdentityPort | None = None,
        attestation_key_id: str = "moderation-1",
        trusted_scanners: set[tuple[str, str]] | None = None,
        trusted_key_ids: set[str] | None = None,
    ) -> None:
        self._service = ModerationService(
            eligible_reviewers=eligible_reviewers,
            local_secret=local_secret,
            signer=signer,
            verifier=verifier,
            reviewer_identity=reviewer_identity,
            contributor_identity=contributor_identity,
            attestation_key_id=attestation_key_id,
            trusted_scanners=trusted_scanners,
            trusted_key_ids=trusted_key_ids,
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
