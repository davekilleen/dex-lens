"""Dex Lens signed Capability Catalog v2 contract.

The catalogue is public Dex product data, fetched only after consent and then
verified locally. Verification fails closed: unsigned, tampered, unknown-key,
malformed, expired, or rollback catalogues produce no usable catalogue.
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.foundations import FoundationCapability

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_CONTRACT_VERSION = "dex-lens-catalogue-v2"
_CACHE_FILE = "lens-catalogue-v2-cache.json"

# Release-owned Dex Core signing keys. M2 will add the real production key id
# after Front Desk/Dave approve signing-key setup; tests inject a local keyring.
PINNED_PUBLIC_KEYS_BY_KEY_ID: dict[str, str] = {}


class CatalogueVerificationError(Exception):
    """A Capability Catalog could not be verified. No catalogue is usable."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogueVerificationError(f"{label} must be a JSON object")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def canonical_signed_payload(envelope: dict[str, Any]) -> bytes:
    """Canonical bytes covered by the catalogue signature.

    The signature covers exactly ``metadata`` and ``catalogue``. The
    ``signature`` field is excluded so the same canonical payload is used by
    the producer and the Lens verifier.
    """
    return _canonical_json_bytes(
        {
            "metadata": envelope.get("metadata"),
            "catalogue": envelope.get("catalogue"),
        }
    )


@dataclass(frozen=True)
class KeyRing:
    """Pinned Dex Core public keys, indexed by ``key_id``."""

    public_keys_b64: dict[str, str]

    def public_key(self, key_id: str) -> Ed25519PublicKey:
        encoded = self.public_keys_b64.get(key_id)
        if encoded is None:
            raise CatalogueVerificationError(f"unknown catalogue signing key_id {key_id!r}")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise CatalogueVerificationError(f"pinned public key {key_id!r} is not base64") from exc
        if len(raw) != 32:
            raise CatalogueVerificationError(f"pinned public key {key_id!r} is not Ed25519 raw")
        return Ed25519PublicKey.from_public_bytes(raw)


def default_keyring() -> KeyRing:
    """The Lens-shipped pinned Dex Core public-key table."""
    return KeyRing(PINNED_PUBLIC_KEYS_BY_KEY_ID)


class CatalogueMetadataV2(InventoriedModel):
    contract_version: Literal["dex-lens-catalogue-v2"]
    catalog_version: int = Field(ge=1)
    produced_at: datetime
    expires_at: datetime
    producer: str = Field(min_length=1, max_length=120)
    core_release: str = Field(min_length=1, max_length=120)
    key_id: str = Field(min_length=1, max_length=120)

    @field_validator("produced_at", "expires_at")
    @classmethod
    def _timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("catalogue timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _expires_after_produced(self) -> CatalogueMetadataV2:
        if self.expires_at <= self.produced_at:
            raise ValueError("catalogue expires_at must be after produced_at")
        return self


class JobTaxonomyEntryV2(InventoriedModel):
    job_id: str = Field(pattern=_ID_RE.pattern)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=600)
    confirmed_gap_signals: tuple[str, ...] = Field(min_length=1, max_length=12)


class CapabilityEvidenceV2(InventoriedModel):
    level: Literal["verified", "supported", "reported", "unknown"]
    source: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    limitations: str = Field(min_length=1, max_length=1000)


class CapabilityCompatibilityV2(InventoriedModel):
    host_adapters: tuple[str, ...] = Field(min_length=1, max_length=20)
    foundation_capabilities: tuple[str, ...] = Field(min_length=1, max_length=20)
    minimum_lens_contract: str = Field(pattern=_SEMVER_RE.pattern)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("host_adapters", "foundation_capabilities")
    @classmethod
    def _ids_are_kebab_case(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not _ID_RE.match(value):
                raise ValueError(f"{value!r} is not a catalogue id")
        if len(set(values)) != len(values):
            raise ValueError("duplicate compatibility id")
        return values

    @field_validator("foundation_capabilities")
    @classmethod
    def _foundation_capabilities_are_known(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        known = {capability.value for capability in FoundationCapability}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"unknown foundation capability id: {', '.join(unknown)}")
        return values


class CapabilityPortableBriefV2(InventoriedModel):
    headline: str = Field(min_length=1, max_length=200)
    adaptation_notes: tuple[str, ...] = Field(min_length=1, max_length=20)
    safety_notes: tuple[str, ...] = Field(min_length=1, max_length=20)
    method_outline: tuple[str, ...] = Field(min_length=1, max_length=20)
    verification_checklist: tuple[str, ...] = Field(min_length=1, max_length=20)
    rollback_advice: str = Field(min_length=1, max_length=1000)


class CatalogueCapabilityEntryV2(InventoriedModel):
    capability_id: str = Field(pattern=_ID_RE.pattern)
    title: str = Field(min_length=1, max_length=140)
    summary: str = Field(min_length=1, max_length=1200)
    value: str = Field(min_length=1, max_length=1200)
    jobs: tuple[str, ...] = Field(min_length=1, max_length=20)
    prerequisites: tuple[str, ...] = Field(min_length=1, max_length=20)
    trade_offs: tuple[str, ...] = Field(min_length=1, max_length=20)
    evidence: tuple[CapabilityEvidenceV2, ...] = Field(min_length=1, max_length=20)
    compatibility: CapabilityCompatibilityV2
    docs_url: str = Field(min_length=1, max_length=300)
    since_release: str = Field(pattern=_SEMVER_RE.pattern)
    changed_in: tuple[str, ...] = Field(max_length=40)
    release_provenance: Literal["core-release"]
    portable_brief: CapabilityPortableBriefV2

    @field_validator("jobs")
    @classmethod
    def _job_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("duplicate job id on capability entry")
        for value in values:
            if not _ID_RE.match(value):
                raise ValueError(f"{value!r} is not a catalogue job id")
        return values

    @field_validator("changed_in")
    @classmethod
    def _changed_versions_are_unique_semver(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("duplicate changed_in version")
        for value in values:
            if not _SEMVER_RE.match(value):
                raise ValueError(f"{value!r} is not a semantic version")
        return values


class PortableBriefContractV2(InventoriedModel):
    format: Literal["markdown"]
    audience: Literal["the person's own AI system"]
    safety_boundary: str = Field(min_length=1, max_length=400)


class CatalogueV2(InventoriedModel):
    jobs_taxonomy: tuple[JobTaxonomyEntryV2, ...] = Field(min_length=1, max_length=80)
    capabilities: tuple[CatalogueCapabilityEntryV2, ...] = Field(min_length=1, max_length=300)
    portable_brief: PortableBriefContractV2

    @model_validator(mode="after")
    def _cross_references_are_closed(self) -> CatalogueV2:
        job_ids = [job.job_id for job in self.jobs_taxonomy]
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("duplicate jobs taxonomy id")
        capability_ids = [capability.capability_id for capability in self.capabilities]
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("duplicate capability id")
        known_jobs = set(job_ids)
        for capability in self.capabilities:
            unknown = sorted(set(capability.jobs) - known_jobs)
            if unknown:
                raise ValueError(
                    f"capability {capability.capability_id!r} references unknown job(s): "
                    f"{', '.join(unknown)}"
                )
        return self


class SignedCatalogueEnvelopeV2(InventoriedModel):
    metadata: CatalogueMetadataV2
    catalogue: CatalogueV2
    signature: str = Field(min_length=1)


class VerifiedCatalogueCacheV2(InventoriedModel):
    verified_envelope_json: str = Field(min_length=1)
    highest_catalog_version: int = Field(ge=1)
    verified_at: datetime

    @field_validator("verified_at")
    @classmethod
    def _verified_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware")
        return value


@dataclass(frozen=True)
class VerifiedCatalogueStateV2:
    status: Literal["verified", "stale"]
    catalogue: SignedCatalogueEnvelopeV2 | None
    message: str


def _parse_envelope(raw_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise CatalogueVerificationError(f"malformed catalogue JSON: {exc.msg}") from exc
    envelope = _require_mapping(parsed, "catalogue envelope")
    for key in ("metadata", "catalogue", "signature"):
        if key not in envelope:
            raise CatalogueVerificationError(f"catalogue envelope missing {key!r}")
    extra = set(envelope) - {"metadata", "catalogue", "signature"}
    if extra:
        raise CatalogueVerificationError(f"catalogue envelope has unknown field(s): {extra}")
    return envelope


def _verify_signature(envelope: dict[str, Any], keyring: KeyRing) -> None:
    metadata = _require_mapping(envelope.get("metadata"), "catalogue metadata")
    key_id = metadata.get("key_id")
    if not isinstance(key_id, str):
        raise CatalogueVerificationError("catalogue metadata key_id must be a string")
    signature_text = envelope.get("signature")
    if not isinstance(signature_text, str):
        raise CatalogueVerificationError("catalogue signature must be a string")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except binascii.Error as exc:
        raise CatalogueVerificationError("catalogue signature is not base64") from exc
    try:
        keyring.public_key(key_id).verify(signature, canonical_signed_payload(envelope))
    except InvalidSignature as exc:
        raise CatalogueVerificationError("catalogue signature verification failed") from exc


def verify_catalogue_envelope(
    raw_json: str,
    *,
    keyring: KeyRing,
    now: datetime | None = None,
    highest_verified_catalog_version: int | None = None,
    allow_expired: bool = False,
) -> SignedCatalogueEnvelopeV2:
    """Verify and parse a signed Catalogue v2 envelope.

    The signature is checked before pydantic model construction, so tampered
    signed bytes fail as a signature failure even if their schema still looks
    valid.
    """
    envelope = _parse_envelope(raw_json)
    _verify_signature(envelope, keyring)
    try:
        verified = SignedCatalogueEnvelopeV2.model_validate(envelope)
    except ValidationError as exc:
        raise CatalogueVerificationError("catalogue schema validation failed") from exc
    current_time = now or _utcnow()
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise CatalogueVerificationError("verification time must be timezone-aware")
    if verified.metadata.contract_version != _CONTRACT_VERSION:
        raise CatalogueVerificationError("catalogue contract version is not supported")
    if verified.metadata.expires_at < current_time and not allow_expired:
        raise CatalogueVerificationError("catalogue has expired")
    if (
        highest_verified_catalog_version is not None
        and verified.metadata.catalog_version < highest_verified_catalog_version
    ):
        raise CatalogueVerificationError(
            f"catalogue rollback refused: version {verified.metadata.catalog_version} "
            f"is older than highest verified version {highest_verified_catalog_version}"
        )
    return verified


def render_capability_entry_html(entry: CatalogueCapabilityEntryV2) -> str:
    """Render a catalogue entry as inert HTML text for local Lens pages."""
    evidence = "".join(
        "<li>"
        f"<strong>{html.escape(item.level)}</strong>: "
        f"{html.escape(item.summary)} "
        f"<span>{html.escape(item.limitations)}</span>"
        "</li>"
        for item in entry.evidence
    )
    notes = "".join(
        f"<li>{html.escape(note)}</li>" for note in entry.portable_brief.adaptation_notes
    )
    return (
        "<article>"
        f"<h2>{html.escape(entry.title)}</h2>"
        f"<p>{html.escape(entry.summary)}</p>"
        f"<h3>{html.escape(entry.portable_brief.headline)}</h3>"
        f"<ul>{evidence}</ul>"
        f"<ol>{notes}</ol>"
        "</article>"
    )


class VerifiedCatalogueStore:
    """Persist and re-verify the last verified public Dex catalogue."""

    def __init__(self, app_storage: Path) -> None:
        self.app_storage = app_storage
        self.cache_path = app_storage / _CACHE_FILE

    def highest_verified_catalog_version(self) -> int | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cache = VerifiedCatalogueCacheV2.model_validate(payload)
        except Exception as exc:
            raise CatalogueVerificationError("stored catalogue cache is unreadable") from exc
        return cache.highest_catalog_version

    def _highest_verified_catalog_version_for_save(self) -> int | None:
        try:
            return self.highest_verified_catalog_version()
        except CatalogueVerificationError:
            return None

    def save_verified(self, verified: SignedCatalogueEnvelopeV2) -> None:
        highest = self._highest_verified_catalog_version_for_save()
        if highest is not None and verified.metadata.catalog_version < highest:
            raise CatalogueVerificationError(
                f"catalogue rollback refused: version {verified.metadata.catalog_version} "
                f"is older than highest verified version {highest}"
            )
        self.app_storage.mkdir(parents=True, exist_ok=True)
        cache = VerifiedCatalogueCacheV2(
            verified_envelope_json=verified.model_dump_json(),
            highest_catalog_version=verified.metadata.catalog_version,
            verified_at=_utcnow(),
        )
        self.cache_path.write_text(
            json.dumps(cache.dump_for_storage(), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def load_last_verified(
        self, *, keyring: KeyRing, now: datetime | None = None
    ) -> SignedCatalogueEnvelopeV2:
        if not self.cache_path.exists():
            raise CatalogueVerificationError("no stored verified catalogue")
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cache = VerifiedCatalogueCacheV2.model_validate(payload)
        except Exception as exc:
            raise CatalogueVerificationError("stored catalogue cache is unreadable") from exc
        return verify_catalogue_envelope(
            cache.verified_envelope_json,
            keyring=keyring,
            now=now,
            highest_verified_catalog_version=cache.highest_catalog_version,
        )

    def load_last_verified_state(
        self, *, keyring: KeyRing, now: datetime | None = None
    ) -> VerifiedCatalogueStateV2:
        if not self.cache_path.exists():
            return VerifiedCatalogueStateV2(
                status="stale",
                catalogue=None,
                message="No Dex catalogue has ever been verified on this machine.",
            )
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cache = VerifiedCatalogueCacheV2.model_validate(payload)
        except Exception as exc:
            raise CatalogueVerificationError("stored catalogue cache is unreadable") from exc
        current_time = now or _utcnow()
        verified = verify_catalogue_envelope(
            cache.verified_envelope_json,
            keyring=keyring,
            now=current_time,
            highest_verified_catalog_version=cache.highest_catalog_version,
            allow_expired=True,
        )
        if verified.metadata.expires_at < current_time:
            return VerifiedCatalogueStateV2(
                status="stale",
                catalogue=verified,
                message=(
                    "Dex catalogue signature is still valid, but the catalogue has expired; "
                    "showing it as stale until Lens can refresh."
                ),
            )
        return VerifiedCatalogueStateV2(
            status="verified",
            catalogue=verified,
            message="Dex catalogue is verified and current.",
        )
