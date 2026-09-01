"""Durable, evidence-bound significant-family reporting and grading."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from tests.diagnosis.test_significant_family_assessment import (
    _catalogue,
    _family,
    _fingerprint,
    _observation,
)

from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    HumanCapability,
)
from capability_exchange.diagnosis.defaults import (
    CachedCatalogueLoader,
    UnknownUntilProposedComparer,
)
from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.diagnosis.report import (
    ReportModel,
    canonical_ledger_appendix,
    canonical_ledger_digest,
    canonical_ledger_payload,
    ledger_appendix_errors,
)
from capability_exchange.diagnosis.run import ENGINE_VERSION, INPUT_SCHEMA_VERSION, RunIdentity
from capability_exchange.evaluation.diagnosis import grade_significant_coverage
from capability_exchange.reports.ledger import load_and_validate_ledger

CATALOGUE_SHA = "a" * 64


def _family_contract() -> dict[str, object]:
    return _family(
        "durable-task-flow",
        profile="mcp",
        members=["dex-work-mcp"],
        components=[
            {"component_type": "capability", "capability_id": "dex-work-mcp"},
            {
                "component_type": "mcp-tool",
                "server_id": "dex-work-mcp",
                "tool_name": "create_task",
            },
        ],
    )


def _family_catalogue():
    return _catalogue(_family_contract())


def _family_fingerprint():
    return _fingerprint(_observation(ObservationKind.MCP_SERVER, "work-mcp"))


def _capabilities(catalogue: object) -> tuple[HumanCapability, ...]:
    return tuple(
        HumanCapability(
            capability_id=item.capability_id,
            title=item.title,
            job_ids=tuple(item.jobs),
            catalogue_ids=(item.capability_id,),
            person_observation_ids=(),
        )
        for item in catalogue.capabilities
    )


def _entries(catalogue: object) -> tuple[CatalogueDisposition, ...]:
    return tuple(
        CatalogueDisposition(
            catalogue_id=item.capability_id,
            capability_id=item.capability_id,
            disposition=Disposition.NOT_ASSESSED,
            reason="No specialist proposal cleared the evidence bar.",
        )
        for item in catalogue.capabilities
    )


def _ledger(*, catalogue_sha256: str = CATALOGUE_SHA) -> ComparisonLedger:
    catalogue = _family_catalogue()
    return ComparisonLedger.for_catalogue_and_fingerprint(
        catalogue,
        fingerprint=_family_fingerprint(),
        catalogue_version=7,
        catalogue_sha256=catalogue_sha256,
        capabilities=_capabilities(catalogue),
        entries=_entries(catalogue),
    )


def _report(ledger: ComparisonLedger) -> str:
    report = ReportModel.from_result(
        run_identity=RunIdentity(
            run_id="run:" + "b" * 16,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            created_at=_family_fingerprint().collected_at,
        ),
        ledger=ledger,
        ledger_sha256=canonical_ledger_digest(ledger),
    )
    return report.render_markdown(ledger)


class _VerifiedStore:
    def __init__(self, catalogue: object) -> None:
        self.envelope = SimpleNamespace(
            catalogue=catalogue,
            metadata=SimpleNamespace(catalog_version=7),
            _signed_json="synthetic-signed-catalogue",
        )

    def load_last_verified(self, **_kwargs: object) -> object:
        return self.envelope


def test_loader_derives_family_contract_presence_from_verified_catalogue() -> None:
    family_store = _VerifiedStore(_family_catalogue())
    family_free_store = _VerifiedStore(_catalogue())

    assert CachedCatalogueLoader(family_store).load(
        run_id="run:" + "c" * 16,
        fingerprint_digest="sha256:" + "d" * 64,
    ).family_contract_present
    assert not CachedCatalogueLoader(family_free_store).load(
        run_id="run:" + "e" * 16,
        fingerprint_digest="sha256:" + "f" * 64,
    ).family_contract_present


def test_comparer_persists_one_exact_evidence_bound_row_per_signed_family() -> None:
    catalogue = _family_catalogue()
    store = _VerifiedStore(catalogue)
    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "1" * 16,
        fingerprint_digest="sha256:" + "2" * 64,
    )

    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=_family_fingerprint(),
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )

    assert [item.family_id for item in ledger.family_entries] == ["durable-task-flow"]
    family = ledger.family_entries[0]
    assert family.title == "Durable Task Flow"
    assert family.disposition.value == "partial-overlap"
    assert family.matched_observation_ids
    assert family.evidence_references
    assert family.unresolved_components == ("mcp-tool:dex-work-mcp:create_task",)
    assert all(not component.method_equivalent for component in family.matched_components)
    assert "1 evidence-backed local building block" in ledger.reciprocal_answer
    assert "does not prove method equivalence, runtime quality, or outcomes" in (
        ledger.reciprocal_answer
    )


def test_family_rows_cannot_be_dropped_or_altered_when_rebound() -> None:
    catalogue = _family_catalogue()
    ledger = _ledger()

    with pytest.raises(ValidationError, match="family entries must equal"):
        ComparisonLedger.for_catalogue(
            catalogue,
            catalogue_version=ledger.catalogue_version,
            catalogue_sha256=ledger.catalogue_sha256,
            capabilities=ledger.capabilities,
            entries=ledger.entries,
            mcp_tools_by_server=ledger.mcp_tools_by_server,
            local_entries=ledger.local_entries,
            family_entries=(),
            reciprocal_answer=ledger.reciprocal_answer,
        )

    changed = ledger.family_entries[0].model_copy(update={"title": "Altered title"})
    with pytest.raises(ValidationError, match="signed family truth"):
        ComparisonLedger.for_catalogue(
            catalogue,
            catalogue_version=ledger.catalogue_version,
            catalogue_sha256=ledger.catalogue_sha256,
            capabilities=ledger.capabilities,
            entries=ledger.entries,
            mcp_tools_by_server=ledger.mcp_tools_by_server,
            local_entries=ledger.local_entries,
            family_entries=(changed,),
            reciprocal_answer=ledger.reciprocal_answer,
        )


def test_family_rows_are_bound_into_payload_digest_and_exact_appendix() -> None:
    ledger = _ledger()
    payload = canonical_ledger_payload(ledger)
    appendix = canonical_ledger_appendix(ledger)

    assert payload["family_entries"][0]["family_id"] == "durable-task-flow"
    assert '"row_type":"family"' in appendix
    assert '"family_id":"durable-task-flow"' in appendix
    assert ledger_appendix_errors(appendix, ledger) == ()

    changed = ledger.model_copy(
        update={
            "family_entries": (
                ledger.family_entries[0].model_copy(
                    update={"reason": "Altered but still bounded reason."}
                ),
            )
        }
    )
    assert canonical_ledger_digest(changed) != canonical_ledger_digest(ledger)
    assert ledger_appendix_errors(appendix, changed)


def test_family_rows_round_trip_through_verified_ledger_reload(tmp_path: Path) -> None:
    signed_json = "synthetic-signed-family-catalogue"
    ledger = _ledger(catalogue_sha256=hashlib.sha256(signed_json.encode()).hexdigest())
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(canonical_ledger_payload(ledger)), encoding="utf-8")
    envelope = SimpleNamespace(
        catalogue=_family_catalogue(),
        metadata=SimpleNamespace(catalog_version=7),
        _signed_json=signed_json,
    )

    loaded, problems = load_and_validate_ledger(path, envelope)

    assert problems == []
    assert loaded is not None
    assert loaded.family_entries == ledger.family_entries
    assert canonical_ledger_digest(loaded) == canonical_ledger_digest(ledger)


def test_report_renders_honest_family_coverage_strength_and_reciprocal_value() -> None:
    ledger = _ledger()
    rendered = _report(ledger)

    assert "## Significant capability coverage" in rendered
    assert "Durable Task Flow" in rendered
    assert "1 component remains Unknown" in rendered
    assert "## What is working especially well" in rendered
    assert "1 evidence-bound building block" in rendered
    assert "## What Dex should learn from you" in rendered
    assert ledger.reciprocal_answer in rendered
    assert "does not establish method equivalence, runtime quality, or outcomes" in rendered
    assert "is absent" not in rendered


def test_grade_is_transparent_and_critical_omissions_fail_regardless_of_total() -> None:
    ledger = _ledger()
    report = _report(ledger)

    passed = grade_significant_coverage(
        fingerprint=_family_fingerprint(),
        ledger=ledger,
        report_markdown=report,
        expected_family_ids=("durable-task-flow",),
        expected_critical_family_ids=("durable-task-flow",),
        unavailable_catalogue_ids=("parked-engine", "dormant-helper"),
        read_only_proven=True,
        run_completed=True,
    )

    assert passed.family_completeness == 30
    assert passed.critical_family_recall == 20
    assert passed.axis_state_honesty == 15
    assert passed.reciprocal_strengths == 15
    assert passed.recommendation_usefulness == 10
    assert passed.privacy_read_only_completion == 10
    assert passed.total == 100
    assert passed.critical_omissions == ()
    assert passed.passed

    omitted = grade_significant_coverage(
        fingerprint=_family_fingerprint(),
        ledger=ledger,
        report_markdown=report,
        expected_family_ids=("durable-task-flow",),
        expected_critical_family_ids=("durable-task-flow", "proactive-health"),
        unavailable_catalogue_ids=("parked-engine", "dormant-helper"),
        read_only_proven=True,
        run_completed=True,
    )
    assert omitted.total >= 90
    assert omitted.critical_omissions == ("proactive-health",)
    assert not omitted.passed


def test_parked_or_dormant_leaf_cannot_be_recommended() -> None:
    catalogue = _family_catalogue()
    entries = tuple(
        item.model_copy(
            update={
                "disposition": Disposition.WORTH_BORROWING,
                "evidence_references": ("evidence:sha256:" + "a" * 64,),
                "reason": "Synthetic evidence proposed this unavailable leaf.",
            }
        )
        if item.catalogue_id == "parked-engine"
        else item
        for item in _entries(catalogue)
    )

    with pytest.raises(ValidationError, match="unavailable catalogue entries"):
        ComparisonLedger.for_catalogue_and_fingerprint(
            catalogue,
            fingerprint=_family_fingerprint(),
            catalogue_version=7,
            catalogue_sha256=hashlib.sha256(b"synthetic").hexdigest(),
            capabilities=_capabilities(catalogue),
            entries=entries,
        )
