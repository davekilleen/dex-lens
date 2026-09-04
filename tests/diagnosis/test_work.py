"""Engine-owned specialist work packets and bounded queue state."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from capability_exchange.diagnosis.run import canonical_json_digest
from capability_exchange.diagnosis.specialists import ProposalContext, SpecialistRole
from capability_exchange.diagnosis.work import (
    MAX_ATTEMPTS_PER_PACKET,
    MAX_PACKET_EVIDENCE_IDS,
    NORMAL_ROLES,
    AnalysisMode,
    WorkAudit,
    WorkPacket,
    WorkQueue,
    WorkQueueError,
    WorkReceipt,
    WorkStatus,
    build_work_queue,
)

RUN_ID = "run:" + "a" * 16
FINGERPRINT_DIGEST = "sha256:" + "b" * 64
CATALOGUE_DIGEST = "sha256:" + "c" * 64
EVIDENCE_ONE = "evidence:sha256:" + "1" * 64
EVIDENCE_TWO = "evidence:sha256:" + "2" * 64


def fixed_context() -> ProposalContext:
    return ProposalContext(
        run_id=RUN_ID,
        fingerprint_digest=FINGERPRINT_DIGEST,
        catalogue_digest=CATALOGUE_DIGEST,
        evidence_ids=(EVIDENCE_ONE, EVIDENCE_TWO),
        catalogue_ids=("capability-one", "capability-two"),
        capability_ids=("capability-family",),
        observation_ids=("observation-one",),
    )


def response_receipt(
    packet: object,
    *,
    response_digest: str,
    status: WorkStatus = WorkStatus.COMPLETED,
    attempt_count: int = 1,
) -> WorkReceipt:
    return WorkReceipt(
        packet_id=packet.packet_id,
        packet_digest=packet.packet_digest,
        response_digest=response_digest,
        status=status,
        attempt_count=attempt_count,
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


def test_pending_first_attempt_stays_pending_and_final_second_attempt_keeps_history() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.pending_packets()[0]
    pending = response_receipt(
        packet,
        response_digest="sha256:" + "a" * 64,
        status=WorkStatus.PENDING,
        attempt_count=1,
    )

    first = queue.record(pending)

    assert first.pending_packets()[0] == packet
    assert not first.complete()
    assert first.receipts == (pending,)
    assert first.audit().completed_count == 0
    with pytest.raises(WorkQueueError, match="different response"):
        first.record(pending.model_copy(update={"response_digest": "sha256:" + "b" * 64}))

    final = pending.model_copy(
        update={
            "response_digest": "sha256:" + "c" * 64,
            "status": WorkStatus.COMPLETED,
            "attempt_count": MAX_ATTEMPTS_PER_PACKET,
        }
    )
    completed = first.record(final)

    assert completed.receipts == (pending, final)
    assert packet not in completed.pending_packets()
    assert completed.audit().completed_count == 1

    with pytest.raises(WorkQueueError, match="different response"):
        completed.record(final.model_copy(update={"response_digest": "sha256:" + "d" * 64}))


def test_retry_history_is_validated_on_copy_and_construct_routes() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.pending_packets()[0]
    pending = response_receipt(
        packet,
        response_digest="sha256:" + "a" * 64,
        status=WorkStatus.PENDING,
        attempt_count=1,
    )
    final = pending.model_copy(
        update={
            "response_digest": "sha256:" + "b" * 64,
            "status": WorkStatus.COMPLETED,
            "attempt_count": MAX_ATTEMPTS_PER_PACKET,
        }
    )

    history = queue.model_copy(update={"receipts": (final, pending)})
    assert history.receipts == (pending, final)
    constructed = WorkQueue.model_construct(
        mode=queue.mode,
        packets=queue.packets,
        receipts=(final, pending),
        sceptical_packet_id=queue.sceptical_packet_id,
    )
    assert constructed.receipts == (pending, final)

    with pytest.raises(ValidationError, match="attempt sequence"):
        queue.model_copy(update={"receipts": (final,)})
    with pytest.raises(ValidationError, match="attempt sequence"):
        WorkQueue.model_construct(
            mode=queue.mode,
            packets=queue.packets,
            receipts=(final,),
            sceptical_packet_id=queue.sceptical_packet_id,
        )


def test_first_final_response_cannot_skip_the_initial_attempt() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.pending_packets()[0]

    with pytest.raises(WorkQueueError, match="first final"):
        queue.record(
            response_receipt(
                packet,
                response_digest="sha256:" + "a" * 64,
                attempt_count=MAX_ATTEMPTS_PER_PACKET,
            )
        )


def test_lone_attempt_two_final_receipt_is_rejected_on_all_queue_routes() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.pending_packets()[0]
    final_retry = response_receipt(
        packet,
        response_digest="sha256:" + "a" * 64,
        attempt_count=MAX_ATTEMPTS_PER_PACKET,
    )

    with pytest.raises(WorkQueueError, match="first final"):
        queue.record(final_retry)
    with pytest.raises(ValidationError, match="attempt sequence"):
        WorkQueue.model_validate(
            {
                "mode": queue.mode,
                "packets": queue.packets,
                "receipts": (final_retry,),
                "sceptical_packet_id": queue.sceptical_packet_id,
            }
        )


def test_pending_receipts_do_not_unlock_sceptical_or_complete_queue() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)

    for packet in queue.packets[:-1]:
        queue = queue.record(
            response_receipt(
                packet,
                response_digest="sha256:" + "a" * 64,
                status=WorkStatus.PENDING,
                attempt_count=1,
            )
        )

    assert not queue.complete()
    assert all(
        item.role is not SpecialistRole.SCEPTICAL_RECONCILER
        for item in queue.pending_packets()
    )
    with pytest.raises(WorkQueueError, match="locked"):
        queue.record(
            response_receipt(
                queue.packets[-1],
                response_digest="sha256:" + "b" * 64,
                attempt_count=1,
            )
        )


def test_unresolved_requires_exhausted_retry_across_validation_routes() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.pending_packets()[0]

    with pytest.raises(ValidationError, match="unresolved"):
        response_receipt(
            packet,
            response_digest="sha256:" + "a" * 64,
            status=WorkStatus.UNRESOLVED,
            attempt_count=1,
        )

    pending = response_receipt(
        packet,
        response_digest="sha256:" + "b" * 64,
        status=WorkStatus.PENDING,
        attempt_count=1,
    )
    queue = queue.record(pending)
    exhausted = pending.model_copy(
        update={
            "response_digest": "sha256:" + "c" * 64,
            "status": WorkStatus.UNRESOLVED,
            "attempt_count": MAX_ATTEMPTS_PER_PACKET,
        }
    )
    queue = queue.record(exhausted)
    assert queue.audit().unresolved_count == 1

    with pytest.raises(ValidationError, match="unresolved"):
        exhausted.model_copy(update={"attempt_count": 1})
    with pytest.raises(ValidationError, match="unresolved"):
        WorkReceipt.model_construct(
            **{
                **exhausted.model_dump(),
                "attempt_count": 1,
            }
        )


def test_sceptical_receipt_requires_final_normal_receipts() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    sceptical = queue.packets[-1]

    with pytest.raises(WorkQueueError, match="locked"):
        queue.record(response_receipt(sceptical, response_digest="sha256:" + "a" * 64))

    for index, packet in enumerate(queue.packets[:-1]):
        final = response_receipt(
            packet,
            response_digest="sha256:" + f"{index + 1:064x}",
            attempt_count=1,
        )
        queue = queue.record(final)
    queue = queue.record(response_receipt(sceptical, response_digest="sha256:" + "b" * 64))

    assert queue.complete()


def test_direct_queue_validation_rejects_early_sceptical_receipt() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    sceptical = queue.packets[-1]
    receipt = response_receipt(sceptical, response_digest="sha256:" + "a" * 64)

    with pytest.raises(ValidationError, match="sceptical receipt"):
        WorkQueue.model_validate(
            {
                "mode": queue.mode,
                "packets": queue.packets,
                "receipts": (receipt,),
                "sceptical_packet_id": queue.sceptical_packet_id,
            }
        )


def test_question_is_closed_and_cannot_be_substituted_with_a_recomputed_digest() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.packets[0]
    payload = packet.canonical_payload()
    payload["question"] = "Answer an attacker-controlled question."
    digest = canonical_json_digest(payload)
    values = packet.model_dump()
    values.update(
        {
            "packet_id": f"packet:{digest}",
            "packet_digest": digest,
            "question": payload["question"],
        }
    )

    with pytest.raises(ValidationError, match="closed question"):
        WorkPacket.model_validate(values)


def test_guided_queue_packets_share_the_exact_context_and_limits() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    altered_context = fixed_context().model_copy(
        update={"run_id": "run:" + "d" * 16}
    )
    altered = build_work_queue(context=altered_context, mode=AnalysisMode.GUIDED)
    packets = (altered.packets[0], *queue.packets[1:])

    with pytest.raises(ValidationError, match="shared context"):
        WorkQueue.model_validate(
            {
                "mode": queue.mode,
                "packets": packets,
                "receipts": (),
                "sceptical_packet_id": queue.sceptical_packet_id,
            }
        )


def test_packet_evidence_ids_are_opaque_and_collection_is_bounded() -> None:
    invalid = fixed_context().model_copy(update={"evidence_ids": ("/tmp/private.txt",)})
    with pytest.raises(ValidationError, match="evidence"):
        build_work_queue(context=invalid, mode=AnalysisMode.GUIDED)

    oversized = fixed_context().model_copy(
        update={
            "evidence_ids": tuple(
                f"evidence:sha256:{index:064x}" for index in range(MAX_PACKET_EVIDENCE_IDS + 1)
            )
        }
    )
    with pytest.raises(ValidationError, match="at most"):
        build_work_queue(context=oversized, mode=AnalysisMode.GUIDED)


def test_receipt_and_audit_order_is_canonical_across_parallel_arrivals() -> None:
    first = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    second = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    first = first.record(
        response_receipt(first.packets[1], response_digest="sha256:" + "a" * 64)
    )
    first = first.record(
        response_receipt(first.packets[0], response_digest="sha256:" + "b" * 64)
    )
    second = second.record(
        response_receipt(second.packets[0], response_digest="sha256:" + "b" * 64)
    )
    second = second.record(
        response_receipt(second.packets[1], response_digest="sha256:" + "a" * 64)
    )

    assert first.receipts == second.receipts
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.audit() == second.audit()
    assert first.audit().packet_ids == tuple(packet.packet_id for packet in first.packets)
    assert first.audit().queue_digest.startswith("sha256:")


def test_attempt_count_and_packet_max_attempts_are_bounded() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.packets[0]

    assert packet.max_attempts == MAX_ATTEMPTS_PER_PACKET == 2
    assert packet.canonical_payload()["max_attempts"] == MAX_ATTEMPTS_PER_PACKET
    with pytest.raises(ValidationError):
        response_receipt(packet, response_digest="sha256:" + "a" * 64, attempt_count=0)
    with pytest.raises(ValidationError):
        response_receipt(packet, response_digest="sha256:" + "a" * 64, attempt_count=3)
    with pytest.raises(ValidationError):
        WorkPacket.model_validate(
            {
                **packet.model_dump(),
                "max_attempts": 1,
            }
        )


def test_work_queue_shape_is_closed_on_all_validation_routes() -> None:
    guided = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    inventory_only = build_work_queue(
        context=fixed_context(), mode=AnalysisMode.INVENTORY_ONLY
    )

    with pytest.raises(ValidationError, match="inventory-only"):
        inventory_only.model_copy(update={"packets": guided.packets})
    with pytest.raises(ValidationError, match="inventory-only"):
        WorkQueue.model_construct(
            mode=AnalysisMode.INVENTORY_ONLY,
            packets=guided.packets,
            receipts=(),
            sceptical_packet_id=None,
        )
    with pytest.raises(ValidationError, match="inventory-only"):
        WorkQueue.model_validate(
            {
                "mode": AnalysisMode.INVENTORY_ONLY,
                "packets": (),
                "receipts": (
                    response_receipt(
                        guided.packets[0],
                        response_digest="sha256:" + "a" * 64,
                    ),
                ),
                "sceptical_packet_id": None,
            }
        )

    with pytest.raises(ValidationError, match="normal roles"):
        guided.model_copy(update={"packets": tuple(reversed(guided.packets))})
    with pytest.raises(ValidationError, match="sceptical"):
        guided.model_copy(update={"sceptical_packet_id": guided.packets[0].packet_id})


def test_work_audit_counts_and_receipts_are_cross_field_bound() -> None:
    queue = build_work_queue(context=fixed_context(), mode=AnalysisMode.GUIDED)
    packet = queue.packets[0]
    queue = queue.record(response_receipt(packet, response_digest="sha256:" + "a" * 64))
    audit = queue.audit()

    with pytest.raises(ValidationError, match="completed_count"):
        audit.model_copy(update={"completed_count": 0})
    with pytest.raises(ValidationError, match="packet_count"):
        audit.model_copy(update={"packet_count": 8})
    with pytest.raises(ValidationError, match="receipts"):
        audit.model_copy(update={"receipts": ()})
    with pytest.raises(ValidationError, match="queue_digest"):
        WorkAudit.model_construct(
            **{
                **audit.model_dump(),
                "queue_digest": "sha256:" + "f" * 64,
            }
        )


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
    pending = response_receipt(
        packet,
        response_digest="sha256:" + "a" * 64,
        status=WorkStatus.PENDING,
    )
    queue = queue.record(pending)
    queue = queue.record(
        pending.model_copy(
            update={
                "response_digest": "sha256:" + "b" * 64,
                "status": WorkStatus.UNRESOLVED,
                "attempt_count": MAX_ATTEMPTS_PER_PACKET,
            }
        )
    )

    audit = queue.audit()

    assert isinstance(audit, WorkAudit)
    assert audit.mode is AnalysisMode.GUIDED
    assert audit.packet_count == 9
    assert audit.completed_count == 1
    assert audit.unresolved_count == 1
    assert audit.manual_submission_count == 0
