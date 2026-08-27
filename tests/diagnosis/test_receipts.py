"""Decision and share receipts: completion claims need local proof."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.diagnosis.test_run import NOW, RUN_ID

from capability_exchange.boundary.serialization import EphemeralByDefaultError
from capability_exchange.diagnosis.receipts import (
    DecisionReceipt,
    DecisionState,
    DestinationClass,
    RecommendationDecision,
    ShareReceipt,
    ShareState,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DISCLOSURE = "a" * 64
RESPONSE_DIGEST = "sha256:" + "b" * 64
SESSION = "session:local-decision"


def decision_receipt(
    *,
    catalogue_id: str = "invented-capability-001",
    state: DecisionState = DecisionState.CHOSEN,
    created_at: datetime = NOW,
    run_id: str = RUN_ID,
) -> DecisionReceipt:
    return DecisionReceipt(
        run_id=run_id,
        catalogue_id=catalogue_id,
        created_at=created_at,
        session_receipt_id=SESSION,
        state=state,
    )


def test_preview_is_not_shared() -> None:
    receipt = ShareReceipt.preview(disclosure_sha256="a" * 64, created_at=NOW)
    assert receipt.state is ShareState.PREVIEWED
    assert not receipt.was_sent


def test_taken_requires_a_local_decision_receipt() -> None:
    with pytest.raises(ValueError, match="decision receipt"):
        RecommendationDecision(
            catalogue_id="invented-capability-001",
            state=DecisionState.CHOSEN,
            receipt=None,
        )


def test_completed_requires_a_local_decision_receipt() -> None:
    with pytest.raises(ValueError, match="decision receipt"):
        RecommendationDecision(
            catalogue_id="invented-capability-001",
            state=DecisionState.COMPLETED,
            receipt=None,
        )


def test_offered_decision_does_not_need_a_receipt() -> None:
    decision = RecommendationDecision(
        catalogue_id="invented-capability-001",
        state=DecisionState.OFFERED,
        receipt=None,
    )

    assert decision.receipt is None
    assert decision.state is DecisionState.OFFERED


def test_chosen_decision_accepts_a_matching_local_receipt() -> None:
    receipt = decision_receipt()
    decision = RecommendationDecision(
        catalogue_id="invented-capability-001",
        state=DecisionState.CHOSEN,
        receipt=receipt,
    )

    assert decision.receipt is receipt
    assert decision.receipt.session_receipt_id == SESSION


def test_share_receipt_cannot_record_not_offered() -> None:
    with pytest.raises(ValueError, match="not-offered"):
        ShareReceipt(
            run_id=RUN_ID,
            disclosure_sha256=DISCLOSURE,
            created_at=NOW,
            session_receipt_id=SESSION,
            state=ShareState.NOT_OFFERED,
        )


def test_sent_requires_destination_class_and_response_digest() -> None:
    with pytest.raises(ValueError, match="destination class"):
        ShareReceipt(
            run_id=RUN_ID,
            disclosure_sha256=DISCLOSURE,
            created_at=NOW,
            session_receipt_id=SESSION,
            state=ShareState.SENT,
            destination_class=None,
            response_receipt_digest=RESPONSE_DIGEST,
        )
    with pytest.raises(ValueError, match="response receipt digest"):
        ShareReceipt(
            run_id=RUN_ID,
            disclosure_sha256=DISCLOSURE,
            created_at=NOW,
            session_receipt_id=SESSION,
            state=ShareState.SENT,
            destination_class=DestinationClass.CONTRIBUTION_INTAKE,
            response_receipt_digest=None,
        )


def test_sent_receipt_records_destination_digest_and_response() -> None:
    receipt = ShareReceipt.sent(
        disclosure_sha256=DISCLOSURE,
        created_at=NOW,
        destination_class=DestinationClass.CONTRIBUTION_INTAKE,
        response_receipt_digest=RESPONSE_DIGEST,
        run_id=RUN_ID,
        session_receipt_id=SESSION,
    )

    assert receipt.state is ShareState.SENT
    assert receipt.was_sent
    assert receipt.destination_class is DestinationClass.CONTRIBUTION_INTAKE
    assert receipt.disclosure_sha256 == DISCLOSURE
    assert receipt.response_receipt_digest == RESPONSE_DIGEST


def test_preview_cannot_carry_a_response_receipt() -> None:
    with pytest.raises(ValueError, match="response receipt digest"):
        ShareReceipt.preview(
            disclosure_sha256=DISCLOSURE,
            created_at=NOW,
            run_id=RUN_ID,
            session_receipt_id=SESSION,
        ).model_copy(update={"response_receipt_digest": RESPONSE_DIGEST})


def test_receipts_reject_naive_timestamps_and_bypasses() -> None:
    naive = datetime(2026, 8, 27, 16, 0)
    receipt = decision_receipt()

    with pytest.raises(ValidationError, match="timezone-aware"):
        receipt.model_copy(update={"created_at": naive})
    with pytest.raises(TypeError, match="validated model_copy"):
        receipt.copy()
    with pytest.raises(ValidationError, match="timezone-aware"):
        DecisionReceipt.model_construct(
            run_id=RUN_ID,
            catalogue_id="invented-capability-001",
            created_at=naive,
            session_receipt_id=SESSION,
            state=DecisionState.CHOSEN,
        )
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        ShareReceipt.preview(
            disclosure_sha256=DISCLOSURE,
            created_at=datetime(2026, 8, 27, 16, 0, tzinfo=timezone(timedelta(hours=1))),
        )


def test_receipts_are_ephemeral_and_closed() -> None:
    preview = ShareReceipt.preview(disclosure_sha256=DISCLOSURE, created_at=NOW)
    decision = RecommendationDecision(
        catalogue_id="invented-capability-001",
        state=DecisionState.CHOSEN,
        receipt=decision_receipt(),
    )

    with pytest.raises(EphemeralByDefaultError):
        preview.dump_for_storage()
    with pytest.raises(EphemeralByDefaultError):
        decision.dump_for_storage()
    with pytest.raises(TypeError, match="validated model_copy"):
        decision.copy()
    assert list(DecisionState) == [
        DecisionState.OFFERED,
        DecisionState.CHOSEN,
        DecisionState.COMPLETED,
    ]
    assert list(ShareState) == [
        ShareState.NOT_OFFERED,
        ShareState.OFFERED,
        ShareState.PREVIEWED,
        ShareState.SENT,
    ]


def test_receipts_and_report_do_not_import_mutation_packages() -> None:
    forbidden = (
        "capability_exchange.adaptation",
        "capability_exchange.contribution",
        "capability_exchange.share",
    )
    for relative in (
        "src/capability_exchange/diagnosis/receipts.py",
        "src/capability_exchange/diagnosis/report.py",
    ):
        tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not any(name == item or name.startswith(f"{item}.") for item in forbidden)


def test_decision_receipt_must_match_catalogue_and_state() -> None:
    receipt = decision_receipt(catalogue_id="invented-capability-002")
    with pytest.raises(ValueError, match="catalogue"):
        RecommendationDecision(
            catalogue_id="invented-capability-001",
            state=DecisionState.CHOSEN,
            receipt=receipt,
        )
    with pytest.raises(ValueError, match="state"):
        RecommendationDecision(
            catalogue_id="invented-capability-002",
            state=DecisionState.COMPLETED,
            receipt=receipt,
        )
