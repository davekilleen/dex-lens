"""Explicit-consent fetch path for the public signed Dex catalogue.

This module is the only Lens-side network doorway for Catalogue v2. It does
not run in the background, does not subscribe, and does not send any private
system information. Callers pass a consent record; the fetcher performs one
anonymous static HTTPS GET, verifies the signed envelope locally, and stores it
only after verification succeeds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import Field, field_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.catalogue.v2 import (
    CatalogueV2,
    CatalogueVerificationError,
    KeyRing,
    SignedCatalogueEnvelopeV2,
    VerifiedCatalogueStore,
    default_keyring,
    verify_catalogue_envelope,
)

DEFAULT_CATALOGUE_URL = "https://heydex.ai/catalogue/dex-lens/v2.json"
CONSENT_STATEMENT = "fetch-public-signed-dex-catalogue"
FETCH_TIMEOUT_SECONDS = 10.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CatalogueFetchStatus(StrEnum):
    VERIFIED = "verified"
    STALE_CACHE = "stale-cache"
    OFFLINE = "offline"
    REFUSED = "refused"


class UrlOpen(Protocol):
    def __call__(self, request: Request, *, timeout: float) -> object:
        """Return a context-manager response with ``read()`` bytes."""


class CatalogueFetchConsent(InventoriedModel):
    """The person explicitly asked Lens to fetch the public Dex catalogue."""

    catalogue_url: str = Field(min_length=1, max_length=400)
    requested_at: datetime
    statement: str

    @field_validator("requested_at")
    @classmethod
    def _requested_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("catalogue consent time must be timezone-aware")
        return value

    @field_validator("statement")
    @classmethod
    def _statement_must_match_button(cls, value: str) -> str:
        if value != CONSENT_STATEMENT:
            raise ValueError("catalogue fetch requires the explicit public-catalogue consent")
        return value

    @field_validator("catalogue_url")
    @classmethod
    def _url_must_be_static_public_dex_https(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https":
            raise ValueError("catalogue fetch requires https")
        if parsed.hostname not in {"heydex.ai", "www.heydex.ai"}:
            raise ValueError("catalogue fetch is pinned to the public Dex host")
        if parsed.username or parsed.password or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("catalogue fetch URL must be a static public GET URL")
        if not parsed.path.endswith(".json"):
            raise ValueError("catalogue fetch URL must point at a static JSON file")
        return value


class CatalogueFetchRecord(InventoriedModel):
    """Non-secret local state for the latest catalogue fetch attempt."""

    status: CatalogueFetchStatus
    message: str = Field(min_length=1, max_length=400)
    catalogue_url: str = Field(min_length=1, max_length=400)
    catalog_version: int | None = Field(default=None, ge=1)
    fetched_at: datetime

    @field_validator("fetched_at")
    @classmethod
    def _fetched_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("catalogue fetch time must be timezone-aware")
        return value


@dataclass(frozen=True, slots=True)
class CatalogueFetchResult:
    status: CatalogueFetchStatus
    message: str
    catalog_version: int | None
    verified: SignedCatalogueEnvelopeV2 | None
    stale: SignedCatalogueEnvelopeV2 | None
    fetched_at: datetime
    catalogue: CatalogueV2 | None = None

    @property
    def usable(self) -> bool:
        return self.status is CatalogueFetchStatus.VERIFIED and (
            self.verified is not None or self.catalogue is not None
        )

    @property
    def display_catalogue(self) -> CatalogueV2 | None:
        if self.catalogue is not None:
            return self.catalogue
        if self.verified is not None:
            return self.verified.catalogue
        if self.stale is not None:
            return self.stale.catalogue
        return None

    def record(self, consent: CatalogueFetchConsent) -> CatalogueFetchRecord:
        return CatalogueFetchRecord(
            status=self.status,
            message=self.message,
            catalogue_url=consent.catalogue_url,
            catalog_version=self.catalog_version,
            fetched_at=self.fetched_at,
        )


class ConsentedCatalogueFetcher:
    """Run one anonymous GET and locally verify the signed catalogue."""

    def __init__(
        self,
        *,
        store: VerifiedCatalogueStore,
        keyring: KeyRing | None = None,
        urlopen: UrlOpen = urlopen,
        now: Callable[[], datetime] | None = None,
        timeout: float = FETCH_TIMEOUT_SECONDS,
    ) -> None:
        self.store = store
        self.keyring = keyring or default_keyring()
        self.urlopen = urlopen
        self.now = now or _utcnow
        self.timeout = timeout

    def fetch(self, consent: CatalogueFetchConsent) -> CatalogueFetchResult:
        fetched_at = self.now()
        try:
            request = Request(
                consent.catalogue_url,
                method="GET",
                headers={"Accept": "application/json"},
            )
            with self.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError, OSError, TimeoutError, UnicodeDecodeError) as exc:
            return self._offline_result(fetched_at, f"offline catalogue fetch: {exc}")

        try:
            verified = verify_catalogue_envelope(
                raw,
                keyring=self.keyring,
                now=fetched_at,
                highest_verified_catalog_version=self.store.highest_verified_catalog_version(),
            )
            self.store.save_verified(verified)
        except CatalogueVerificationError as exc:
            return CatalogueFetchResult(
                status=CatalogueFetchStatus.REFUSED,
                message=f"catalogue refused: {exc}",
                catalog_version=None,
                verified=None,
                stale=None,
                fetched_at=fetched_at,
            )
        return CatalogueFetchResult(
            status=CatalogueFetchStatus.VERIFIED,
            message="catalogue verified locally",
            catalog_version=verified.metadata.catalog_version,
            verified=verified,
            stale=None,
            fetched_at=fetched_at,
            catalogue=verified.catalogue,
        )

    def _offline_result(self, fetched_at: datetime, message: str) -> CatalogueFetchResult:
        try:
            stale = self.store.load_last_verified_stale(keyring=self.keyring)
        except CatalogueVerificationError:
            return CatalogueFetchResult(
                status=CatalogueFetchStatus.OFFLINE,
                message=message,
                catalog_version=None,
                verified=None,
                stale=None,
                fetched_at=fetched_at,
            )
        return CatalogueFetchResult(
            status=CatalogueFetchStatus.STALE_CACHE,
            message=f"{message}; showing last verified catalogue as stale",
            catalog_version=stale.metadata.catalog_version,
            verified=None,
            stale=stale,
            fetched_at=fetched_at,
            catalogue=stale.catalogue,
        )
