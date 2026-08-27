"""Local consent is the only way to issue a diagnosis scope receipt."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.concierge.test_local_server import RunningServer, envelope

from capability_exchange.concierge.collection import ScopeSnapshot
from capability_exchange.concierge.consent import (
    InMemoryConsentStore,
    LocalScopeConsentAuthority,
)
from capability_exchange.concierge.server import ConciergeSession
from capability_exchange.diagnosis.run import DiagnosisStage, DiagnosisStateError


def private_storage() -> InMemoryConsentStore:
    return InMemoryConsentStore()


def invented_root(tmp_path: Path) -> Path:
    root = tmp_path / "invented-vault"
    root.mkdir()
    (root / "README.md").write_text("invented\n", encoding="utf-8")
    return root


def approved_scope_snapshot(root: Path) -> ScopeSnapshot:
    return ScopeSnapshot.capture((root,))


def test_only_local_consent_authority_can_issue_scope_receipt(tmp_path: Path) -> None:
    authority = LocalScopeConsentAuthority(storage=private_storage())
    root = invented_root(tmp_path)
    request = authority.prepare(candidate_roots=(root,))

    assert request.stage is DiagnosisStage.CREATED
    assert authority.receipt_for(request.run_id) is None
    receipt = authority.approve_from_local_session(
        run_id=request.run_id,
        scope_snapshot=approved_scope_snapshot(root),
        authenticated_session_id="local-session",
    )
    assert receipt.run_id == request.run_id
    assert authority.receipt_for(request.run_id) == receipt
    assert receipt.scope_references == (
        approved_scope_snapshot(root).source_descriptors[0].scope_reference,
    )


def test_prepare_does_not_snapshot_approved_root_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[object] = []
    original = ScopeSnapshot.capture

    def forbidden(*args: object, **kwargs: object) -> ScopeSnapshot:
        captured.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(ScopeSnapshot, "capture", forbidden)
    authority = LocalScopeConsentAuthority(storage=private_storage())
    authority.prepare(candidate_roots=(invented_root(tmp_path),))

    assert captured == []


def test_prepare_does_not_accept_empty_or_duplicate_roots(tmp_path: Path) -> None:
    authority = LocalScopeConsentAuthority(storage=private_storage())
    root = invented_root(tmp_path)

    with pytest.raises(DiagnosisStateError, match="candidate root"):
        authority.prepare(candidate_roots=())
    with pytest.raises(DiagnosisStateError, match="distinct"):
        authority.prepare(candidate_roots=(root, root))


def test_unauthenticated_session_cannot_issue_a_receipt(tmp_path: Path) -> None:
    authority = LocalScopeConsentAuthority(storage=private_storage())
    root = invented_root(tmp_path)
    request = authority.prepare(candidate_roots=(root,))

    with pytest.raises(DiagnosisStateError, match="authenticated local session"):
        authority.approve_from_local_session(
            run_id=request.run_id,
            scope_snapshot=approved_scope_snapshot(root),
            authenticated_session_id="   ",
        )
    with pytest.raises(DiagnosisStateError, match="unknown diagnosis run"):
        authority.approve_from_local_session(
            run_id="run:" + "0" * 16,
            scope_snapshot=approved_scope_snapshot(root),
            authenticated_session_id="local-session",
        )


def test_approve_route_issues_receipt_only_when_session_is_authenticated(
    tmp_path: Path,
) -> None:
    root = invented_root(tmp_path)
    authority = LocalScopeConsentAuthority(
        storage=private_storage(),
        now=lambda: datetime(2026, 8, 27, 16, 0, tzinfo=UTC),
    )
    prepared = authority.prepare(candidate_roots=(root,))

    with RunningServer(envelope, approved_root=root) as running:
        running.session.diagnosis_consent = authority
        running.session.diagnosis_run_id = prepared.run_id
        running.bootstrap()
        assert authority.receipt_for(prepared.run_id) is None
        status, _, body = running.post("/approve")
        assert status == 200, body
        receipt = authority.receipt_for(prepared.run_id)
        assert receipt is not None
        assert receipt.run_id == prepared.run_id
        assert receipt.session_receipt_id.startswith("session:")


def test_session_without_diagnosis_run_keeps_existing_approve_behaviour(
    tmp_path: Path,
) -> None:
    session = ConciergeSession(
        approved_roots=(invented_root(tmp_path),),
        collector=lambda **kwargs: envelope(),
    )
    assert session.diagnosis_consent is None
    assert session.diagnosis_run_id is None
