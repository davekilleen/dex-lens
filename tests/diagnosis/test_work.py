"""Engine-owned specialist work packets and bounded queue state."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from capability_exchange.diagnosis.run import canonical_json_digest
from capability_exchange.diagnosis.specialists import ProposalContext, SpecialistRole
from capability_exchange.diagnosis.work import (
    NORMAL_ROLES,
    AnalysisMode,
    WorkAudit,
    WorkQueueError,
    WorkReceipt,
    WorkStatus,
    build_work_queue,
)

RUN_ID = "run:" + "a" * 16
FINGERPRINT_DIGEST = "sha256:" + "b" * 64
CATALOGUE_DIGEST = "sha256:" + "c" * 64


def fixed_context() -> ProposalContext:
    return ProposalContext(
        run_id=RUN_ID,
        fingerprint_digest=FINGERPRINT_DIGEST,
        catalogue_digest=CATALOGUE_DIGEST,
        evidence_ids=("evidence:one", "evidence:two"),
        catalogue_ids=("capability-one", "capability-two"),
        capability_ids=("capability-family",),
        observation_ids=("observation-one",),
    )


def response_receipt(
    packet: object,
    *,
    response_digest: str,
    status: WorkStatus = WorkStatus.COMPLETED,
) -> WorkReceipt:
    return WorkReceipt(
        packet_id=packet.packet_id,
        packet_digest=packet.packet_digest,
        response_digest=response_digest,
        status=status,
        proposal_count=0,
    )


def test_inventory_only_queue_emits_no_packets() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.INVENTORY_ONLY)

    assert queue.packets == ()
    assert queue.pending_packets() == ()
    assert queue.complete()
    assert queue.sceptical_packet_id is None


def test_guided_queue_issues_normal_roles_before_sceptical_review() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)

    assert tuple(packet.role for packet in queue.pending_packets()) == NORMAL_ROLES
    assert SpecialistRole.SCEPTICAL_RECONCILER not in {
        packet.role for packet in queue.pending_packets()
    }
    assert len(queue.packets) == len(NORMAL_ROLES) + 1
    assert queue.packets[-1].role is SpecialistRole.SCEPTICAL_RECONCILER
    assert queue.sceptical_packet_id == queue.packets[-1].packet_id


def test_sceptical_packet_unlocks_only_after_all_normal_receipts() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)

    with pytest.raises(WorkQueueError, match="locked"):
        queue.require_pending(queue.sceptical_packet_id or "")

    for index, packet in enumerate(queue.packets[:-1]):
        queue = queue.record(
            response_receipt(packet, response_digest="sha256:" + f"{index + 1:064x}")
        )

    pending = queue.pending_packets()
    assert len(pending) == 1
    assert pending[0].role is SpecialistRole.SCEPTICAL_RECONCILER


def test_same_response_is_idempotent_but_changed_response_is_refused() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.pending_packets()[0]
    receipt = response_receipt(packet, response_digest="sha256:" + "a" * 64)

    once = queue.record(receipt)

    assert once.record(receipt) == once
    with pytest.raises(WorkQueueError, match="different response"):
        once.record(response_receipt(packet, response_digest="sha256:" + "b" * 64))


def test_packet_mismatch_is_refused() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.pending_packets()[0]
    receipt = response_receipt(packet, response_digest="sha256:" + "a" * 64).model_copy(
        update={"packet_digest": "sha256:" + "d" * 64}
    )

    with pytest.raises(WorkQueueError, match="packet digest"):
        queue.record(receipt)


def test_packet_identity_and_digest_bind_role_and_allowed_identities() -> None:
    first = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    changed_context = fixed_context().model_copy(
        update={"catalogue_ids": ("capability-one", "capability-three")}
    )
    second = build_work_queue(context=changed_context, mode=AnalysisMode.GUIDED)

    assert first.packets[0].packet_id != second.packets[0].packet_id
    assert first.packets[0].packet_digest != second.packets[0].packet_digest
    assert first.packets[0].packet_id.startswith("packet:sha256:")
    assert first.packets[0].packet_digest == canonical_json_digest(
        first.packets[0].canonical_payload()
    )


def test_work_models_are_immutable_and_statuses_are_closed() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.packets[0]

    with pytest.raises(ValidationError):
        response_receipt(packet, response_digest="sha256:" + "a" * 64, status="unknown")
    with pytest.raises(ValidationError):
        packet.model_copy(update={"max_proposals": 25})
    with pytest.raises(TypeError, match="validated model_copy"):
        packet.copy()


def test_work_audit_counts_unresolved_receipts() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.packets[0]
    queue = queue.record(
        response_receipt(
            packet,
            response_digest="sha256:" + "a" * 64,
            status=WorkStatus.UNRESOLVED,
        )
    )

    audit = queue.audit()

    assert isinstance(audit, WorkAudit)
    assert audit.mode is AnalysisMode.GUIDED
    assert audit.packet_count == 9
    assert audit.completed_count == 1
    assert audit.unresolved_count == 1
    assert audit.manual_submission_count == 0
