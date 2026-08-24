"""What actually changed in the catalogue since this machine last looked.

A recurring check is only worth keeping if it stays quiet, and it can only
stay quiet if it knows what "new" means. Dex's published entries record the
Dex Core release they changed in, not the catalogue version, so the catalogue
cannot answer "what is new since version 3" out of its own contents.

It does not have to. What Lens saw last time is knowable *here*: take a
fingerprint of every published entry when it is shown, keep the fingerprints
in app storage, and compare on the next run. That gives a true per-entry
delta — this one is new, that one was reworded — without asking Dex for
anything and without keeping any of the person's material.

Two honest limits, both stated wherever this is used:

- The comparison is against what *this machine* has seen. A capability
  published and changed before Lens ever ran here looks unchanged, because
  from this machine's point of view it is.
- A fingerprint changes when the published text changes, so a reworded
  summary counts as a change. Better a change reported that turns out to be
  cosmetic than one silently dropped.

Only public catalogue text is fingerprinted. Nothing about the person's system
is read, held, or compared here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from capability_exchange.catalogue.v2 import CatalogueV2

__all__ = [
    "CatalogueDelta",
    "CatalogueSnapshot",
    "CatalogueSnapshotStore",
    "compare_with_snapshot",
    "entry_fingerprints",
]

SNAPSHOT_FILE = "lens-catalogue-seen-entries.json"


def entry_fingerprints(catalogue: CatalogueV2) -> dict[str, str]:
    """One short fingerprint per published capability, by id."""
    return {
        entry.capability_id: hashlib.sha256(
            entry.model_dump_json().encode("utf-8")
        ).hexdigest()
        for entry in catalogue.capabilities
    }


@dataclass(frozen=True)
class CatalogueSnapshot:
    """The published entries this machine has already been shown."""

    catalog_version: int | None = None
    fingerprints: dict[str, str] | None = None

    @property
    def is_empty(self) -> bool:
        return not self.fingerprints


@dataclass(frozen=True)
class CatalogueDelta:
    """What moved between the last snapshot and the catalogue in hand."""

    added: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.changed or self.removed)

    @property
    def worth_reading(self) -> tuple[str, ...]:
        """The ids a person would actually want to look at: new, then changed.

        Removals are reported but not fetched: there is nothing to read, and a
        digest of things that no longer exist is not a recommendation.
        """
        return (*self.added, *self.changed)

    def summary(self) -> str:
        """One line of plain words, for a person who ran a scheduled check."""
        parts = []
        if self.added:
            parts.append(f"{len(self.added)} new")
        if self.changed:
            parts.append(f"{len(self.changed)} changed")
        if self.removed:
            parts.append(f"{len(self.removed)} withdrawn")
        return ", ".join(parts) if parts else "nothing new"


def compare_with_snapshot(
    catalogue: CatalogueV2, snapshot: CatalogueSnapshot
) -> CatalogueDelta:
    """The delta between what was seen and what is published now."""
    seen = snapshot.fingerprints or {}
    now = entry_fingerprints(catalogue)
    return CatalogueDelta(
        added=tuple(sorted(set(now) - set(seen))),
        changed=tuple(
            sorted(key for key, digest in now.items() if key in seen and seen[key] != digest)
        ),
        removed=tuple(sorted(set(seen) - set(now))),
    )


class CatalogueSnapshotStore:
    """Read and write the fingerprints of the entries last shown here."""

    def __init__(self, app_storage: Path) -> None:
        self.app_storage = app_storage
        self.path = app_storage / SNAPSHOT_FILE

    def load(self) -> CatalogueSnapshot:
        """The last snapshot, or an empty one.

        An unreadable snapshot is treated as no snapshot rather than an error.
        The worst it can cause is one noisy run, and refusing to print a
        verified catalogue because a local convenience file is corrupt would
        be the wrong trade every time.
        """
        if not self.path.exists():
            return CatalogueSnapshot()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            fingerprints = payload["fingerprints"]
            if not isinstance(fingerprints, dict):
                raise TypeError("fingerprints must be an object")
            return CatalogueSnapshot(
                catalog_version=payload.get("catalog_version"),
                fingerprints={str(key): str(value) for key, value in fingerprints.items()},
            )
        except (OSError, ValueError, KeyError, TypeError):
            return CatalogueSnapshot()

    def save(self, catalogue: CatalogueV2, *, catalog_version: int) -> CatalogueSnapshot:
        snapshot = CatalogueSnapshot(
            catalog_version=catalog_version,
            fingerprints=entry_fingerprints(catalogue),
        )
        self.app_storage.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "catalog_version": snapshot.catalog_version,
                    "fingerprints": snapshot.fingerprints,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        return snapshot
