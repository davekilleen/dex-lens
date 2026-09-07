"""Durable, evidence-bound significant-family reporting and grading."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from tests.catalogue.test_bridge import _catalogue as _legacy_skill_catalogue
from tests.diagnosis.test_significant_family_assessment import (
    _catalogue,
    _family,
    _fingerprint,
    _observation,
)

from capability_exchange.diagnosis import defaults
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
from capability_exchange.diagnosis.observations import (
    ObservationKind,
    OperationalState,
    SafeAttribute,
)
from capability_exchange.diagnosis.report import (
    ReportModel,
    canonical_ledger_appendix,
    canonical_ledger_digest,
    canonical_ledger_payload,
    ledger_appendix_errors,
)
from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    INPUT_SCHEMA_VERSION,
    DiagnosisStateError,
    RunIdentity,
)
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


def _ledger(
    *,
    catalogue_sha256: str = CATALOGUE_SHA,
    fingerprint=None,
    recommend: bool = False,
    disposition_updates: dict[str, Disposition] | None = None,
) -> ComparisonLedger:
    catalogue = _family_catalogue()
    entries = _entries(catalogue)
    if recommend:
        entries = tuple(
            item.model_copy(
                update={
                    "disposition": Disposition.WORTH_BORROWING,
                    "evidence_references": ("evidence:sha256:" + "c" * 64,),
                    "reason": "Outcome evidence leaves one useful Dex addition.",
                }
            )
            if item.catalogue_id == "dex-work-mcp"
            else item
            for item in entries
        )
    if disposition_updates:
        entries = tuple(
            item.model_copy(
                update={
                    "disposition": disposition_updates[item.catalogue_id],
                    "evidence_references": ("evidence:sha256:" + "d" * 64,),
                    "method_compared": (
                        disposition_updates[item.catalogue_id]
                        is Disposition.DEX_SHOULD_LEARN
                    ),
                    "reason": f"Reviewed evidence for {item.catalogue_id}.",
                }
            )
            if item.catalogue_id in disposition_updates
            else item
            for item in entries
        )
    return ComparisonLedger.for_catalogue_and_fingerprint(
        catalogue,
        fingerprint=fingerprint or _family_fingerprint(),
        catalogue_version=7,
        catalogue_sha256=catalogue_sha256,
        capabilities=_capabilities(catalogue),
        entries=entries,
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
    def __init__(
        self,
        catalogue: object,
        *,
        version: int = 7,
        core_release: str = "v1.97.6",
    ) -> None:
        self.envelope = SimpleNamespace(
            catalogue=catalogue,
            metadata=SimpleNamespace(
                catalog_version=version,
                core_release=core_release,
            ),
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


def test_skills_only_cache_uses_the_verified_bundled_four_class_fallback() -> None:
    store = _VerifiedStore(_legacy_skill_catalogue(), version=6)
    fingerprint = _family_fingerprint()

    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "a" * 16,
        fingerprint_digest="sha256:" + "b" * 64,
    )
    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )

    assert slice_.version == 6
    assert "dex-career-mcp" in slice_.catalogue_ids
    assert {item.catalogue_id for item in ledger.entries} == set(slice_.catalogue_ids)
    assert len(ledger.mcp_tools_by_server) >= 10
    assert not slice_.family_contract_present


def test_expired_bundled_reference_cannot_be_used_for_current_diagnosis() -> None:
    after_bundled_expiry = datetime(2026, 9, 27, tzinfo=UTC)

    with pytest.raises(DiagnosisStateError, match="current diagnosis"):
        defaults._load_bundled_reference(now=after_bundled_expiry)


def test_partial_enriched_catalogue_fails_closed_instead_of_omitting_classes() -> None:
    catalogue = _family_catalogue()
    partial = catalogue.model_copy(
        update={
            "capabilities": tuple(
                item
                for item in catalogue.capabilities
                if item.capability_class in {"active-skill", "mcp-server"}
            )
        }
    )

    with pytest.raises(DiagnosisStateError, match="incomplete capability classes"):
        CachedCatalogueLoader(_VerifiedStore(partial)).load(
            run_id="run:" + "3" * 16,
            fingerprint_digest="sha256:" + "4" * 64,
        )


def test_mixed_legacy_and_enriched_skills_fail_closed() -> None:
    legacy = _legacy_skill_catalogue()
    enriched_skill = next(
        item
        for item in _family_catalogue().capabilities
        if item.capability_class == "active-skill"
    )
    mixed = legacy.model_copy(
        update={"capabilities": (legacy.capabilities[0], enriched_skill)}
    )

    with pytest.raises(DiagnosisStateError, match="mixes legacy and enriched"):
        CachedCatalogueLoader(_VerifiedStore(mixed)).load(
            run_id="run:" + "7" * 16,
            fingerprint_digest="sha256:" + "8" * 64,
        )


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
    assert "1 evidence-bound local building block" in ledger.reciprocal_answer
    assert "These are exact configuration matches" in ledger.reciprocal_answer
    assert "What Dex should learn remains Unknown" in ledger.reciprocal_answer


@pytest.mark.parametrize("inspected_version", ("v1.80.0", "v1.80.0-beta.1"))
def test_release_number_without_signed_lineage_does_not_invent_family_changes(
    inspected_version: str,
) -> None:
    catalogue = _family_catalogue()
    store = _VerifiedStore(catalogue, core_release="v1.97.6")
    release = _observation(ObservationKind.RELEASE, "dex-core").model_copy(
        update={"attributes": (SafeAttribute(key="release-id", value=inspected_version),)}
    )
    fingerprint = _fingerprint(
        _observation(ObservationKind.MCP_SERVER, "work-mcp"),
        release,
    )
    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "3" * 16,
        fingerprint_digest="sha256:" + "4" * 64,
    )

    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )
    rendered = _report(ledger)

    assert "## What has changed since your version" not in rendered
    assert "## Current Dex compared with your identified release" not in rendered


def test_signed_skill_lineage_renders_exact_family_changes() -> None:
    family = _family(
        "recent-workflow",
        profile=None,
        members=["workflow-skill"],
        components=[{"component_type": "capability", "capability_id": "workflow-skill"}],
    )
    payload = _catalogue(family).model_dump(mode="json")
    workflow = next(
        item for item in payload["capabilities"] if item["capability_id"] == "workflow-skill"
    )
    workflow["since_release"] = "1.90.0"
    catalogue = type(_catalogue()).model_validate(payload)
    store = _VerifiedStore(catalogue, core_release="v1.97.6")
    release = _observation(ObservationKind.RELEASE, "dex-core").model_copy(
        update={"attributes": (SafeAttribute(key="release-id", value="v1.80.0"),)}
    )
    fingerprint = _fingerprint(release)
    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "5" * 16,
        fingerprint_digest="sha256:" + "6" * 64,
    )

    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )
    rendered = _report(ledger)

    assert ledger.version_distance is not None
    assert ledger.version_distance.families[0].introduced_member_ids == ("workflow-skill",)
    assert "## What has changed since your identified Dex release" in rendered
    assert "New signed skill entries: `workflow-skill`." in rendered
    assert "families without signed lineage are omitted, not treated as unchanged" in rendered


def test_version_distance_rejects_forged_release_evidence_on_reload(
    tmp_path: Path,
) -> None:
    family = _family(
        "recent-workflow",
        profile=None,
        members=["workflow-skill"],
        components=[{"component_type": "capability", "capability_id": "workflow-skill"}],
    )
    payload = _catalogue(family).model_dump(mode="json")
    workflow = next(
        item for item in payload["capabilities"] if item["capability_id"] == "workflow-skill"
    )
    workflow["since_release"] = "1.90.0"
    catalogue = type(_catalogue()).model_validate(payload)
    store = _VerifiedStore(catalogue, core_release="v1.97.6")
    release = _observation(ObservationKind.RELEASE, "dex-core").model_copy(
        update={"attributes": (SafeAttribute(key="release-id", value="v1.80.0"),)}
    )
    fingerprint = _fingerprint(release)
    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "7" * 16,
        fingerprint_digest="sha256:" + "8" * 64,
    )
    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )
    stored = canonical_ledger_payload(ledger)
    assert stored["version_distance"] is not None
    stored["version_distance"]["evidence_references"] = ["file-token:invented"]
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(stored), encoding="utf-8")

    loaded, problems = load_and_validate_ledger(path, store.envelope)

    assert loaded is None
    assert any("release evidence" in problem for problem in problems)


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
    assert "- Durable Task Flow: 1 of 2 published building blocks" in rendered
    assert "## What Dex should learn from you" in rendered
    assert ledger.reciprocal_answer in rendered
    assert "does not establish method equivalence, runtime quality, or outcomes" in rendered
    assert "is absent" not in rendered


def test_coverage_summary_exposes_unmatched_local_and_mcp_tool_counts() -> None:
    rendered = _report(_ledger())

    assert "- Local observations: 1 captured; 0 mapped; 1 remains not assessed." in rendered
    assert (
        "- Signed MCP inventory: 1 declared tool across 1 server; 1 complete "
        "inventory; 0 sampled inventories."
        in rendered
    )
    assert "- Significant-family components: 1 exact match; 1 remains Unknown." in rendered


def test_configuration_only_overlap_is_not_claimed_as_working() -> None:
    catalogue = _family_catalogue()
    store = _VerifiedStore(catalogue)
    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "9" * 16,
        fingerprint_digest="sha256:" + "8" * 64,
    )
    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=_family_fingerprint(),
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )
    rendered = _report(ledger)

    assert (
        "cannot prove that a capability is working especially well because "
        "the matched building block has no verified outcome or health evidence"
        in rendered
    )
    assert "## What is clearly built" in rendered
    assert "That is evidence of real foundations in this area." not in rendered
    assert "What Dex should learn remains Unknown" in ledger.reciprocal_answer


def test_verified_outcome_evidence_can_ground_a_working_strength() -> None:
    catalogue = _family_catalogue()
    store = _VerifiedStore(catalogue)
    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "7" * 16,
        fingerprint_digest="sha256:" + "6" * 64,
    )
    fingerprint = _fingerprint(
        _observation(
            ObservationKind.MCP_SERVER,
            "work-mcp",
            state=OperationalState.OUTCOME_VERIFIED,
        )
    )
    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )
    rendered = _report(ledger)

    assert (
        "This snapshot provides verified outcome or health evidence for 1 matched "
        "building block."
        in rendered
    )
    assert "outcome- or health-verified local building block" in ledger.reciprocal_answer
    assert "What Dex should learn remains Unknown" in ledger.reciprocal_answer


def test_close_repeats_the_ledger_strength_and_first_recommendation() -> None:
    fingerprint = _fingerprint(
        _observation(
            ObservationKind.MCP_SERVER,
            "work-mcp",
            state=OperationalState.OUTCOME_VERIFIED,
        )
    )
    rendered = _report(_ledger(fingerprint=fingerprint, recommend=True))

    assert (
        "- Already doing: 1 matched building block has verified outcome or health "
        "evidence."
        in rendered
    )
    assert "- First move: Consider `dex-work-mcp`." in rendered
    assert "No grounded strength cleared the evidence bar." not in rendered


def test_close_does_not_invent_priority_between_multiple_recommendations() -> None:
    rendered = _report(
        _ledger(
            disposition_updates={
                "dex-work-mcp": Disposition.WORTH_BORROWING,
                "workflow-skill": Disposition.WORTH_BORROWING,
            }
        )
    )

    assert (
        "- First move: No single first move has stronger evidence than the other "
        "options above."
        in rendered
    )
    assert "- First move: Consider `dex-work-mcp`." not in rendered


def test_close_names_one_uniquely_best_supported_first_move() -> None:
    fingerprint = _fingerprint(
        _observation(ObservationKind.MCP_SERVER, "work-mcp")
    )
    ledger = _ledger(
        fingerprint=fingerprint,
        disposition_updates={
            "dex-work-mcp": Disposition.WORTH_BORROWING,
            "workflow-skill": Disposition.WORTH_BORROWING,
        },
    )
    observation_id = ledger.local_entries[0].observation_id
    capabilities = tuple(
        item.model_copy(update={"person_observation_ids": (observation_id,)})
        if item.capability_id == "dex-work-mcp"
        else item
        for item in ledger.capabilities
    )
    ranked = ledger.model_copy(update={"capabilities": capabilities})

    rendered = _report(ranked)

    assert "- First move: Consider `dex-work-mcp` (the best-supported option)." in rendered


def test_report_explains_each_evidence_backed_recommendation() -> None:
    ledger = _ledger(recommend=True)
    rendered = _report(ledger)
    human_report = rendered.split("## Complete ledger appendix", maxsplit=1)[0]

    assert "## Worth borrowing from Dex" in rendered
    assert "### Dex Work Mcp (`dex-work-mcp`)" in rendered
    assert "Outcome evidence leaves one useful Dex addition." in rendered
    assert "evidence:sha256:" not in human_report
    assert (
        "Evidence: 1 approved observation; exact references are in the appendix."
        in human_report
    )
    assert "evidence:sha256:" + "c" * 64 in rendered
    assert "## Considered and rejected" in rendered


def test_report_keeps_the_two_way_sections_in_human_order() -> None:
    rendered = _report(_ledger())
    headings = (
        "## What I read",
        "## What is working especially well",
        "## What Dex should learn from you",
        "## Worth borrowing from Dex",
        "## Fragility and contradictions",
        "## Coverage and limits",
        "## What happens next",
    )

    assert all(heading in rendered for heading in headings)
    positions = [rendered.index(heading) for heading in headings]

    assert positions == sorted(positions)


def test_report_surfaces_reviewed_strength_learning_and_fragility() -> None:
    ledger = _ledger(
        disposition_updates={
            "workflow-skill": Disposition.STRONG_HERE,
            "dormant-helper": Disposition.DEX_SHOULD_LEARN,
            "parked-engine": Disposition.FRAGILE_OR_CONTRADICTORY,
        }
    )
    rendered = _report(ledger)

    assert "### Workflow Skill (`workflow-skill`)" in rendered
    assert "### Dormant Helper (`dormant-helper`)" in rendered
    assert "### Parked Engine (`parked-engine`)" in rendered
    assert rendered.count("evidence:sha256:" + "d" * 64) >= 3
    assert "- Dex should learn: See 1 evidence-reviewed pattern above." in rendered
    reciprocal_section = rendered.split("## What Dex should learn from you", maxsplit=1)[
        1
    ].split("## Worth borrowing from Dex", maxsplit=1)[0]
    assert "remains Unknown" not in reciprocal_section
    assert "The evidence-reviewed pattern below cleared that stricter bar." in reciprocal_section
    grade = grade_significant_coverage(
        fingerprint=_family_fingerprint(),
        ledger=ledger,
        report_markdown=rendered,
        expected_family_ids=("durable-task-flow",),
        expected_critical_family_ids=("durable-task-flow",),
        read_only_proven=True,
        run_completed=True,
    )
    assert grade.reciprocal_strengths == 10


def test_grade_is_transparent_and_critical_omissions_fail_regardless_of_total() -> None:
    fingerprint = _fingerprint(
        _observation(
            ObservationKind.MCP_SERVER,
            "work-mcp",
            state=OperationalState.OUTCOME_VERIFIED,
        )
    )
    ledger = _ledger(fingerprint=fingerprint, recommend=True)
    report = _report(ledger)

    passed = grade_significant_coverage(
        fingerprint=fingerprint,
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
        fingerprint=fingerprint,
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


def test_grade_is_withheld_when_the_signed_family_contract_is_absent() -> None:
    catalogue = _catalogue()
    store = _VerifiedStore(catalogue)
    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "5" * 16,
        fingerprint_digest="sha256:" + "4" * 64,
    )
    fingerprint = _family_fingerprint()
    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )

    grade = grade_significant_coverage(
        fingerprint=fingerprint,
        ledger=ledger,
        report_markdown=_report(ledger),
        expected_family_ids=(),
        expected_critical_family_ids=(),
        read_only_proven=True,
        run_completed=True,
    )

    assert grade.total is None
    assert grade.withheld_reason == (
        "The signed catalogue has no significant-family contract; a coverage score "
        "would be misleading."
    )
    assert not grade.passed


def test_zero_recommendations_do_not_earn_usefulness_points() -> None:
    ledger = _ledger()

    grade = grade_significant_coverage(
        fingerprint=_family_fingerprint(),
        ledger=ledger,
        report_markdown=_report(ledger),
        expected_family_ids=("durable-task-flow",),
        expected_critical_family_ids=("durable-task-flow",),
        read_only_proven=True,
        run_completed=True,
    )

    assert grade.recommendation_usefulness == 0


def test_configuration_only_overlap_cannot_earn_full_strength_points() -> None:
    ledger = _ledger()

    grade = grade_significant_coverage(
        fingerprint=_family_fingerprint(),
        ledger=ledger,
        report_markdown=_report(ledger),
        expected_family_ids=("durable-task-flow",),
        expected_critical_family_ids=("durable-task-flow",),
        read_only_proven=True,
        run_completed=True,
    )

    assert grade.reciprocal_strengths == 10


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
