"""Durable local subscription state for explicit Dex catalogue updates.

This module stores only non-secret app state outside inspected roots. It does
not fetch anything itself; callers use the existing consented fetch doorway and
this record only answers whether a future Lens run may perform that one public
catalogue GET automatically.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.catalogue.fetch import DEFAULT_CATALOGUE_URL

SUBSCRIPTION_FILE = "lens-catalogue-v2-subscription.json"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def default_lens_app_storage(
    approved_roots: Iterable[Path] = (),
    *,
    environ: dict[str, str] | None = None,
) -> Path:
    """Return the app-owned state directory and prove it is outside read scope."""

    env = os.environ if environ is None else environ
    base = Path(env.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    storage = (base / "dex-lens" / "capability-bridge").expanduser().resolve(strict=False)
    require_app_storage_outside_roots(storage, tuple(approved_roots))
    return storage


def require_app_storage_outside_roots(app_storage: Path, approved_roots: Iterable[Path]) -> None:
    storage = app_storage.expanduser().resolve(strict=False)
    for root in approved_roots:
        candidate = Path(root).expanduser().resolve(strict=False)
        if storage == candidate or storage.is_relative_to(candidate):
            raise ValueError("Dex Lens app storage must be outside the approved read scope")


class CatalogueSubscriptionRecord(InventoriedModel):
    """Non-secret local opt-in state for public catalogue update checks."""

    subscribed: bool = False
    catalogue_url: str = Field(default=DEFAULT_CATALOGUE_URL, min_length=1, max_length=400)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_seen_catalog_version: int | None = Field(default=None, ge=1)
    parked_catalog_version: int | None = Field(default=None, ge=1)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamp_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("catalogue subscription timestamps must be timezone-aware")
        return value

    @field_validator("catalogue_url")
    @classmethod
    def _url_must_be_static_public_dex_https(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https":
            raise ValueError("catalogue subscription requires https")
        if parsed.hostname not in {"heydex.ai", "www.heydex.ai"}:
            raise ValueError("catalogue subscription is pinned to the public Dex host")
        if parsed.username or parsed.password or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("catalogue subscription URL must be a static public GET URL")
        if not parsed.path.endswith(".json"):
            raise ValueError("catalogue subscription URL must point at a static JSON file")
        return value


class CatalogueSubscriptionStore:
    """Read/write the single local subscription record."""

    def __init__(self, app_storage: Path) -> None:
        self.app_storage = app_storage
        self.path = app_storage / SUBSCRIPTION_FILE

    def load(self) -> CatalogueSubscriptionRecord:
        if not self.path.exists():
            return CatalogueSubscriptionRecord()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return CatalogueSubscriptionRecord.model_validate(payload)
        except Exception as exc:
            raise ValueError("stored catalogue subscription is unreadable") from exc

    def _save(self, record: CatalogueSubscriptionRecord) -> CatalogueSubscriptionRecord:
        self.app_storage.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(record.dump_for_storage(), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return record

    def subscribe(
        self,
        *,
        catalogue_url: str = DEFAULT_CATALOGUE_URL,
        now: datetime | None = None,
    ) -> CatalogueSubscriptionRecord:
        current = self.load()
        timestamp = now or _utcnow()
        return self._save(
            CatalogueSubscriptionRecord(
                subscribed=True,
                catalogue_url=catalogue_url,
                created_at=current.created_at or timestamp,
                updated_at=timestamp,
                last_seen_catalog_version=current.last_seen_catalog_version,
                parked_catalog_version=None,
            )
        )

    def revoke(self, *, now: datetime | None = None) -> CatalogueSubscriptionRecord:
        _ = now  # retained for API symmetry and future audit text.
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        if self.path.exists():
            raise ValueError("catalogue subscription file survived revocation")
        return CatalogueSubscriptionRecord()

    def mark_seen(
        self, *, catalog_version: int, now: datetime | None = None
    ) -> CatalogueSubscriptionRecord:
        current = self.load()
        if not current.subscribed:
            return current
        return self._save(
            current.model_copy(
                update={
                    "updated_at": now or _utcnow(),
                    "last_seen_catalog_version": catalog_version,
                    "parked_catalog_version": None,
                }
            )
        )

    def record_seen(
        self, *, catalog_version: int, now: datetime | None = None
    ) -> CatalogueSubscriptionRecord:
        """Remember the catalogue version this machine has now been shown.

        Deliberately not :meth:`mark_seen`, which only records for a subscribed
        machine because it drives the browser journey's update prompt. This one
        records the baseline whether or not anyone subscribed to anything: it
        exists so a later ``dex-lens catalogue --since-last`` knows what was
        already seen without a person having to memorise a version number.
        Recording that a public, identical-for-everyone list was displayed says
        nothing about the person, and it never turns on a network request.
        """
        current = self.load()
        return self._save(
            current.model_copy(
                update={
                    "updated_at": now or _utcnow(),
                    "last_seen_catalog_version": catalog_version,
                    "parked_catalog_version": None,
                }
            )
        )

    def park(
        self, *, catalog_version: int, now: datetime | None = None
    ) -> CatalogueSubscriptionRecord:
        current = self.load()
        if not current.subscribed:
            return current
        return self._save(
            current.model_copy(
                update={
                    "updated_at": now or _utcnow(),
                    "parked_catalog_version": catalog_version,
                }
            )
        )

    def should_prompt(self, *, catalog_version: int) -> bool:
        current = self.load()
        if not current.subscribed:
            return False
        last_seen = current.last_seen_catalog_version
        if last_seen is None or catalog_version <= last_seen:
            return False
        return current.parked_catalog_version != catalog_version
