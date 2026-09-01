"""Every verified Dex catalogue entry receives one explicit disposition."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.catalogue.test_bridge import _catalogue

from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    HumanCapability,
)

CATALOGUE_SHA = "a" * 64


def _human(*catalogue_ids: str) -> HumanCapability:
    return HumanCapability(
        capability_id="system-health",
        title="System health",
        job_ids=("check-system-health",),
        catalogue_ids=catalogue_ids,
        person_observation_ids=("health-check:system-doctor",),
    )


def _disposition(
    catalogue_id: str,
    disposition: Disposition = Disposition.NOT_ASSESSED,
    *,
    evidence: tuple[str, ...] = (),
    method_compared: bool = False,
) -> CatalogueDisposition:
    return CatalogueDisposition(
        catalogue_id=catalogue_id,
        disposition=disposition,
        capability_id="system-health",
        evidence_references=evidence,
        method_compared=method_compared,
        reason="Checked against the local evidence available for this job.",
    )


def test_ledger_requires_one_disposition_per_catalogue_entry() -> None:
    catalogue = _catalogue()
    first = catalogue.capabilities[0].capability_id

    with pytest.raises(ValidationError, match="catalogue identity set"):
        ComparisonLedger.for_catalogue(
            catalogue,
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=(_human(first),),
            entries=(_disposition(first),),
        )


def test_ledger_refuses_more_than_three_recommendations() -> None:
    entries = tuple(
        _disposition(
            f"catalogue-item-{index}",
            Disposition.WORTH_BORROWING,
            evidence=(f"path-token:item-{index}",),
            method_compared=True,
        )
        for index in range(4)
    )

    with pytest.raises(ValidationError, match="at most three"):
        ComparisonLedger(
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=(_human(*(item.catalogue_id for item in entries)),),
            entries=entries,
            reciprocal_answer="No transferable method cleared the evidence bar.",
        )


def test_same_name_without_method_evidence_cannot_be_shared() -> None:
    with pytest.raises(ValidationError, match="method evidence"):
        _disposition(
            "system-doctor",
            Disposition.SHARED,
            evidence=("path-token:doctor",),
        )


def test_dex_should_learn_requires_compared_method_evidence() -> None:
    with pytest.raises(ValidationError, match="Dex-should-learn requires method evidence"):
        _disposition(
            "system-doctor",
            Disposition.DEX_SHOULD_LEARN,
            evidence=("path-token:doctor",),
        )


def test_scored_disposition_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="requires evidence"):
        _disposition("backup-proof", Disposition.STRONG_HERE)


def test_complete_catalogue_identity_set_is_accepted() -> None:
    catalogue = _catalogue()
    catalogue_ids = tuple(item.capability_id for item in catalogue.capabilities)
    ledger = ComparisonLedger.for_catalogue(
        catalogue,
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=(_human(*catalogue_ids),),
        entries=tuple(_disposition(item) for item in catalogue_ids),
    )

    assert {entry.catalogue_id for entry in ledger.entries} == set(catalogue_ids)
    assert ledger.reciprocal_answer == "No transferable method cleared the evidence bar."


def test_human_capability_cannot_point_at_an_unknown_catalogue_entry() -> None:
    catalogue = _catalogue()
    catalogue_ids = tuple(item.capability_id for item in catalogue.capabilities)

    with pytest.raises(ValidationError, match="unknown catalogue IDs"):
        ComparisonLedger.for_catalogue(
            catalogue,
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=(_human(*catalogue_ids, "not-in-catalogue"),),
            entries=tuple(_disposition(item) for item in catalogue_ids),
        )
