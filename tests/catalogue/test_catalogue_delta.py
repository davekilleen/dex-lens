"""Knowing what is new without asking Dex what is new.

Published entries record the Dex Core release they changed in, not the
catalogue version, so the catalogue cannot answer "what is new since version
3" from its own contents. It does not have to: what this machine has already
seen is knowable here. These tests hold down the three things that makes
true — the fingerprint is stable, the comparison is honest about all three
directions, and a corrupt snapshot costs one noisy run rather than the
command.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.catalogue.test_v2_verifier import unsigned_envelope

from capability_exchange.catalogue.delta import (
    CatalogueSnapshot,
    CatalogueSnapshotStore,
    compare_with_snapshot,
    entry_fingerprints,
)
from capability_exchange.catalogue.v2 import CatalogueV2


def _catalogue(**changes: object) -> CatalogueV2:
    payload = unsigned_envelope(version=7)["catalogue"]
    payload = json.loads(json.dumps(payload))
    payload["capabilities"][0].update(changes)
    return CatalogueV2.model_validate(payload)


class TestFingerprints:
    def test_the_same_catalogue_fingerprints_the_same_way(self) -> None:
        """A fingerprint that moved on its own would report a change a week."""
        assert entry_fingerprints(_catalogue()) == entry_fingerprints(_catalogue())

    def test_a_reworded_entry_gets_a_different_fingerprint(self) -> None:
        original = entry_fingerprints(_catalogue())
        reworded = entry_fingerprints(_catalogue(value="Something else entirely."))

        assert original != reworded
        assert set(original) == set(reworded), "the id did not change, the text did"


class TestComparing:
    def test_no_snapshot_makes_everything_new(self) -> None:
        delta = compare_with_snapshot(_catalogue(), CatalogueSnapshot())

        assert delta.added == ("dex-durable-memory-provenance",)
        assert not delta.is_empty

    def test_an_identical_catalogue_is_empty(self) -> None:
        catalogue = _catalogue()
        snapshot = CatalogueSnapshot(7, entry_fingerprints(catalogue))

        assert compare_with_snapshot(catalogue, snapshot).is_empty

    def test_it_separates_new_from_changed_from_withdrawn(self) -> None:
        catalogue = _catalogue()
        snapshot = CatalogueSnapshot(
            6,
            {"dex-durable-memory-provenance": "f" * 64, "dex-retired": "a" * 64},
        )

        delta = compare_with_snapshot(catalogue, snapshot)

        assert delta.changed == ("dex-durable-memory-provenance",)
        assert delta.removed == ("dex-retired",)
        assert delta.added == ()
        assert delta.summary() == "1 changed, 1 withdrawn"

    def test_only_the_readable_ones_are_offered_to_read(self) -> None:
        """There is nothing to read about a capability that no longer exists."""
        snapshot = CatalogueSnapshot(6, {"dex-retired": "a" * 64})

        delta = compare_with_snapshot(_catalogue(), snapshot)

        assert "dex-retired" not in delta.worth_reading
        assert delta.worth_reading == ("dex-durable-memory-provenance",)


class TestTheSnapshotOnDisk:
    def test_it_round_trips(self, tmp_path: Path) -> None:
        store = CatalogueSnapshotStore(tmp_path / "state")
        catalogue = _catalogue()

        store.save(catalogue, catalog_version=7)

        loaded = store.load()
        assert loaded.catalog_version == 7
        assert loaded.fingerprints == entry_fingerprints(catalogue)

    def test_it_holds_fingerprints_and_no_catalogue_text(self, tmp_path: Path) -> None:
        """It exists to answer one question; it should carry nothing else."""
        store = CatalogueSnapshotStore(tmp_path / "state")
        store.save(_catalogue(), catalog_version=7)

        written = store.path.read_text(encoding="utf-8")

        assert "Durable Memory" not in written
        assert "dex-durable-memory-provenance" in written

    def test_nothing_saved_yet_is_an_empty_snapshot(self, tmp_path: Path) -> None:
        assert CatalogueSnapshotStore(tmp_path / "state").load().is_empty

    def test_a_corrupt_snapshot_reads_as_no_snapshot(self, tmp_path: Path) -> None:
        """One noisy run beats refusing to print a verified catalogue."""
        store = CatalogueSnapshotStore(tmp_path / "state")
        store.app_storage.mkdir(parents=True)
        store.path.write_text("{ not json", encoding="utf-8")

        assert store.load().is_empty
