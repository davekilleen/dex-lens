"""Process-default engine construction and durable scope approval."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.concierge.test_diagnosis_consent import invented_root
from tests.diagnosis.test_run import RUN_ID, approved_receipt

from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.defaults import (
    ConsentBoundCollector,
    build_default_engine,
    dispositions_from_proposals,
)
from capability_exchange.diagnosis.orchestrator import DeterministicDiagnosisEngine
from capability_exchange.diagnosis.run import DiagnosisStateError
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    DISAGREEMENT_REASON,
    ProposalKind,
    ValidatedProposal,
)

_EVIDENCE = "evidence:sha256:" + ("ab" * 32)


def _proposal(
    *,
    catalogue_id: str = "cap-one",
    capability_id: str = "cap-one",
    disposition: Disposition = Disposition.STRONG_HERE,
    kind: ProposalKind = ProposalKind.STRENGTH,
    reason: str = "Quoted local evidence supports this strength.",
) -> ValidatedProposal:
    return ValidatedProposal(
        kind=kind,
        catalogue_id=catalogue_id,
        capability_id=capability_id,
        disposition=disposition,
        evidence_ids=(_EVIDENCE,),
        reason=reason,
    )


def test_build_default_engine_uses_app_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    engine = build_default_engine()
    assert isinstance(engine, DeterministicDiagnosisEngine)
    assert engine.consent_authority is not None
    assert engine.run_store.storage.is_relative_to((tmp_path / "state").resolve())


def test_collector_refuses_before_persisted_approval(tmp_path: Path) -> None:
    store = DiagnosisRunStore(tmp_path / "runs")
    collector = ConsentBoundCollector(store)
    with pytest.raises(DiagnosisStateError, match="approve the exact scope"):
        collector.collect(approved_receipt())


def test_scope_approval_round_trips(tmp_path: Path) -> None:
    store = DiagnosisRunStore(tmp_path / "runs")
    root = invented_root(tmp_path)
    receipt = approved_receipt()
    store.save_scope_approval(receipt, approved_roots=(str(root),))
    loaded = store.load_scope_approval(RUN_ID)
    assert loaded is not None
    assert loaded.receipt == receipt
    assert loaded.approved_roots == (str(root),)
    assert store.list_resumable() == ()


def test_unproposed_identities_stay_not_assessed() -> None:
    entries = dispositions_from_proposals(("cap-one", "cap-two"), ())
    assert [item.disposition for item in entries] == [
        Disposition.NOT_ASSESSED,
        Disposition.NOT_ASSESSED,
    ]
    assert all("cleared the evidence bar" in item.reason for item in entries)


def test_agreed_proposal_fills_one_disposition() -> None:
    entries = dispositions_from_proposals(("cap-one",), (_proposal(),))
    assert entries[0].disposition is Disposition.STRONG_HERE
    assert entries[0].evidence_references == (_EVIDENCE,)


def test_conflicting_kinds_for_one_id_remain_unknown() -> None:
    entries = dispositions_from_proposals(
        ("cap-one",),
        (
            _proposal(),
            _proposal(
                kind=ProposalKind.FRAGILITY,
                disposition=Disposition.FRAGILE_OR_CONTRADICTORY,
                reason="The same file also contradicts the claim.",
            ),
        ),
    )
    assert entries[0].disposition is Disposition.NOT_ASSESSED
    assert entries[0].reason == DISAGREEMENT_REASON
