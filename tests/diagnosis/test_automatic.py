"""Conservative automatic recommendation rules."""

from __future__ import annotations

from tests.diagnosis.test_significant_family_assessment import (
    _family,
    _fingerprint,
    _job,
    _observation,
    _skill,
)

from capability_exchange.diagnosis.automatic import build_automatic_candidates
from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.diagnosis.significant_families import assess_significant_families
from capability_exchange.diagnosis.workflows import WorkflowGraph


def available_backup_catalogue():
    from tests.diagnosis.test_significant_family_assessment import (
        _automation,
        _mcp,
        _parked_engine,
    )

    from capability_exchange.catalogue.v2 import CatalogueV2

    family = _family(
        "backup-and-restore-confidence",
        profile="filesystem",
        members=["backup-restore"],
        components=[{"component_type": "capability", "capability_id": "backup-restore"}],
    )
    return CatalogueV2.model_validate(
        {
            "jobs_taxonomy": [_job()],
            "capabilities": [
                _skill("backup-restore"),
                _skill("workflow-skill"),
                _skill("dormant-helper", availability="dormant"),
                _mcp(),
                _automation(),
                _parked_engine(),
            ],
            "capability_aliases": [
                {"alias": "work-mcp", "capability_id": "dex-work-mcp"},
                {"alias": "workflow-alias", "capability_id": "workflow-skill"},
            ],
            "capability_families": [family],
            "portable_brief": {
                "format": "markdown",
                "audience": "the person's own AI system",
                "safety_boundary": "guidance only; it changes nothing",
            },
        }
    )


def configured_backup_without_restore_proof():
    return _fingerprint(_observation(ObservationKind.SKILL, "backup-restore"))


def test_restore_is_suggested_only_when_backup_work_is_relevant() -> None:
    catalogue = available_backup_catalogue()
    fingerprint = configured_backup_without_restore_proof()
    assessments = assess_significant_families(catalogue, fingerprint)
    candidates = build_automatic_candidates(
        catalogue=catalogue,
        fingerprint=fingerprint,
        workflows=WorkflowGraph(nodes=(), edges=()),
        family_assessments=assessments,
    )
    assert [item.catalogue_id for item in candidates] == ["backup-restore"]
