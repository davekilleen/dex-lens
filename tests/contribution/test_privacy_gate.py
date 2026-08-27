"""Fable S1/S2/S4 contribution privacy and abstraction contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.cards.test_model import make_card

from capability_exchange.boundary.deletion import run_deletion_path
from capability_exchange.contribution.privacy import (
    LOOKS_PERSONAL_CONFIRMATION,
    ContributionDeclineStore,
    ContributionPrivacyGate,
    SensitiveCategory,
    candidate_from_proposal,
    user_initiated_candidate,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState
from capability_exchange.jobs import CandidateJobProposal

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _proposal(*, reference: str = "file:skills#snap:private-canary") -> CandidateJobProposal:
    return CandidateJobProposal(
        candidate_id="recurring-skill-workflows",
        title="Possible job: run your recurring skill-based workflows",
        draft_situation="You appear to run repeated workflows through saved skills",
        draft_desired_outcome="Your recurring workflows run dependably",
        rationale="inferred from non-raw evidence; a suggestion, not a fact",
        evidence=(
            EvidenceItem(
                state=EvidenceState.INFERRED,
                captured_at=NOW,
                reference=reference,
            ),
        ),
    )


def test_candidate_uses_only_non_raw_proposal_and_evidence_primitives() -> None:
    private_reference = "file:client-zephyr/oncology-checkin.md#snap:secret"

    candidate = candidate_from_proposal(_proposal(reference=private_reference))
    rendered = repr(candidate) + json.dumps(candidate.model_dump(mode="json"))

    assert candidate.pattern_id == "recurring-workflow-pattern"
    assert candidate.candidate_digest.startswith("sha256:")
    assert candidate.retained_primitives == (
        "repeatable workflow shape",
        "inferred non-raw evidence state",
    )
    assert private_reference not in rendered
    assert "oncology" not in rendered
    assert "client-zephyr" not in rendered


@pytest.mark.parametrize(
    ("private_text", "category"),
    (
        ("Cancer medication check-in for sentinel-health at 08:30", SensitiveCategory.HEALTH),
        ("Care reminder for my daughter sentinel-family", SensitiveCategory.FAMILY_CARE),
        ("Review mortgage and account balance for sentinel-finance", SensitiveCategory.FINANCES),
        ("Manager performance review for sentinel-personnel", SensitiveCategory.PERSONNEL),
        ("Weekly report for Sentinel Meridian Ltd", SensitiveCategory.NAMED_COMPANY),
    ),
)
def test_sensitive_categories_are_detected_without_echoing_matched_text(
    private_text: str,
    category: SensitiveCategory,
) -> None:
    gate = ContributionPrivacyGate()
    candidate = candidate_from_proposal(_proposal())
    card = make_card(method=private_text)

    preview = gate.preview(candidate, card)
    serialized = json.dumps(preview.model_dump(mode="json"), sort_keys=True)

    assert preview.looks_personal is True
    assert category in preview.sensitive_categories
    assert private_text not in serialized
    assert private_text not in repr(preview)
    assert "sentinel-" not in serialized
    assert preview.confirmation_statement == LOOKS_PERSONAL_CONFIRMATION


def test_personal_card_becomes_a_structural_abstraction_not_a_redacted_copy() -> None:
    gate = ContributionPrivacyGate()
    candidate = candidate_from_proposal(_proposal())
    private_text = "Text Sarah at Acme Oncology Ltd about her chemotherapy at 08:30"
    card = make_card(
        selected_job="family-care",
        method=private_text,
        desired_outcome="Sarah receives her cancer medication reminder",
    )

    preview = gate.preview(candidate, card)
    abstract_json = preview.abstract_card.model_dump_json()

    assert preview.looks_personal is True
    assert preview.retained == (
        "closed Capability Card structure",
        "version number",
        "permission choices",
        "test-state label",
        "inferred non-raw evidence basis",
    )
    assert "all source prose, names, schedules, organisations, and file material" in (
        preview.removed
    )
    for private_fragment in ("Sarah", "Acme", "Oncology", "chemotherapy", "08:30"):
        assert private_fragment not in abstract_json
    assert gate.require_minimized(preview.abstract_card) == preview.abstract_card


def test_raw_prose_or_files_are_not_representable_in_the_abstraction() -> None:
    gate = ContributionPrivacyGate()
    candidate = candidate_from_proposal(_proposal())
    payload = make_card().model_dump(mode="json")
    payload["raw_prose"] = "the private source prose"
    payload["source_files"] = ["/home/person/private.md"]

    with pytest.raises(ValueError, match="structured Capability Card"):
        gate.preview(candidate, payload)


def test_literal_source_prose_is_replaced_before_any_disclosure_body() -> None:
    gate = ContributionPrivacyGate()
    candidate = candidate_from_proposal(_proposal())
    source_text = "Source file contents: def send_private_notes(value): return value"

    preview = gate.preview(candidate, make_card(method=source_text))

    assert preview.looks_personal is True
    assert source_text not in preview.abstract_card.model_dump_json()
    assert "send_private_notes" not in preview.abstract_card.model_dump_json()
    assert gate.require_minimized(preview.abstract_card) == preview.abstract_card


def test_decline_persists_only_the_opaque_digest_and_suppresses_a_fresh_store(
    tmp_path: Path,
) -> None:
    inspected = tmp_path / "inspected"
    inspected.mkdir()
    app_storage = tmp_path / "app-storage"
    candidate = candidate_from_proposal(_proposal())
    store = ContributionDeclineStore(
        app_storage / "contribution-candidate-declines.json",
        inspected_roots=(inspected,),
    )

    store.decline(candidate)

    raw = (app_storage / "contribution-candidate-declines.json").read_text(
        encoding="utf-8"
    )
    assert json.loads(raw) == {
        "candidate_digests": [candidate.candidate_digest],
        "schema_version": 1,
    }
    assert "recurring" not in raw
    assert "private-canary" not in raw
    recovered = ContributionDeclineStore(
        app_storage / "contribution-candidate-declines.json",
        inspected_roots=(inspected,),
    )
    assert recovered.is_declined(candidate)

    removed = run_deletion_path("delete-contribution-candidate-declines", app_storage)
    assert removed == [app_storage / "contribution-candidate-declines.json"]
    assert not (app_storage / "contribution-candidate-declines.json").exists()


def test_decline_store_refuses_to_live_inside_an_inspected_root(tmp_path: Path) -> None:
    inspected = tmp_path / "inspected"
    inspected.mkdir()

    with pytest.raises(ValueError, match="outside inspected roots"):
        ContributionDeclineStore(
            inspected / "contribution-candidate-declines.json",
            inspected_roots=(inspected,),
        )


def test_fresh_process_reads_decline_and_suppresses_the_same_candidate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "app-storage" / "contribution-candidate-declines.json"
    ContributionDeclineStore(path).decline(user_initiated_candidate())
    environment = dict(os.environ)
    environment["PYTHONPATH"] = "src"
    script = (
        "from pathlib import Path; "
        "from capability_exchange.contribution.privacy import "
        "ContributionDeclineStore, user_initiated_candidate; "
        f"store = ContributionDeclineStore(Path({str(path)!r})); "
        "print(store.is_declined(user_initiated_candidate()))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "True"
