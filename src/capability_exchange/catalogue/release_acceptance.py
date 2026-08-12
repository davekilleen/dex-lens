"""Exact identity check for a signed Dex Core catalogue release.

Signature and schema verification establish that Dex Core signed a valid
catalogue.  This module adds the release-lane assertion: the signed catalogue
must also be the exact release, byte payload, version, and complete contents
that the caller intended to certify.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from capability_exchange.catalogue.v2 import SignedCatalogueEnvelopeV2

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CATALOGUE_ID = re.compile(r"^[a-z][a-z0-9-]{2,80}$")


class CatalogueReleaseMismatch(RuntimeError):
    """A valid signed catalogue is not the exact release being certified."""


@dataclass(frozen=True)
class CatalogueReleaseExpectation:
    """Caller-owned identity for one catalogue release acceptance run."""

    core_release: str
    key_id: str
    raw_sha256: str
    catalog_version: int
    capability_count: int
    job_count: int
    capability_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.core_release.strip():
            raise ValueError("core_release must be non-empty")
        if not self.key_id.strip():
            raise ValueError("key_id must be non-empty")
        if _HEX_SHA256.fullmatch(self.raw_sha256) is None:
            raise ValueError("raw_sha256 must be a lowercase sha256 digest")
        if type(self.catalog_version) is not int or self.catalog_version <= 0:
            raise ValueError("catalog_version must be a positive integer")
        if type(self.job_count) is not int or self.job_count <= 0:
            raise ValueError("job_count must be a positive integer")
        if not self.capability_ids:
            raise ValueError("capability_ids must be non-empty")
        if len(set(self.capability_ids)) != len(self.capability_ids):
            raise ValueError("capability_ids must be unique")
        if any(_CATALOGUE_ID.fullmatch(item) is None for item in self.capability_ids):
            raise ValueError("capability_ids must contain catalogue ids")
        if type(self.capability_count) is not int or self.capability_count <= 0:
            raise ValueError("capability_count must be a positive integer")
        if len(self.capability_ids) != self.capability_count:
            raise ValueError("capability_count must equal the complete capability_ids set")


@dataclass(frozen=True)
class CatalogueReleaseObservation:
    """Observed identity returned only after every release assertion passes."""

    core_release: str
    key_id: str
    raw_sha256: str
    catalog_version: int
    capability_ids: tuple[str, ...]
    job_count: int


def _mismatch(label: str, expected: object, observed: object) -> CatalogueReleaseMismatch:
    return CatalogueReleaseMismatch(
        f"unexpected {label}: expected {expected!r}, observed {observed!r}"
    )


def assert_catalogue_release(
    raw_bytes: bytes,
    verified: SignedCatalogueEnvelopeV2,
    expected: CatalogueReleaseExpectation,
) -> CatalogueReleaseObservation:
    """Return observed identity only when it exactly matches ``expected``.

    ``verified`` must already have passed the pinned-key signature and schema
    verifier.  Raw bytes are required separately because semantically
    equivalent JSON is not byte-identical to the release artifact.
    """

    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if raw_sha256 != expected.raw_sha256:
        raise _mismatch("sha256", expected.raw_sha256, raw_sha256)

    metadata = verified.metadata
    catalogue = verified.catalogue
    capability_ids = tuple(
        capability.capability_id for capability in catalogue.capabilities
    )
    job_count = len(catalogue.jobs_taxonomy)

    if metadata.core_release != expected.core_release:
        raise _mismatch("core release", expected.core_release, metadata.core_release)
    if metadata.key_id != expected.key_id:
        raise _mismatch("key id", expected.key_id, metadata.key_id)
    if metadata.catalog_version != expected.catalog_version:
        raise _mismatch(
            "catalog version", expected.catalog_version, metadata.catalog_version
        )
    if len(capability_ids) != expected.capability_count:
        raise _mismatch(
            "capability count", expected.capability_count, len(capability_ids)
        )
    if capability_ids != expected.capability_ids:
        raise _mismatch("capability ids", expected.capability_ids, capability_ids)
    if job_count != expected.job_count:
        raise _mismatch("job count", expected.job_count, job_count)

    return CatalogueReleaseObservation(
        core_release=metadata.core_release,
        key_id=metadata.key_id,
        raw_sha256=raw_sha256,
        catalog_version=metadata.catalog_version,
        capability_ids=capability_ids,
        job_count=job_count,
    )
