"""Engine-owned, immutable specialist work packets.

The diagnosis engine issues a closed set of bounded assignments.  A host
assistant may process those assignments in any order it likes, but the queue
owns packet identity, the allowed identity set, and completion.  Responses
are represented by immutable receipts so replaying the same response is safe
while a changed response or stale packet is refused.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from capability_exchange.diagnosis.run import _ValidatedInventoried, canonical_json_digest
from capability_exchange.diagnosis.specialists import SpecialistRole

__all__ = [
    "MAX_ATTEMPTS_PER_PACKET",
    "MAX_PROPOSALS_PER_PACKET",
    "NORMAL_ROLES",
    "AnalysisMode",
    "WorkAudit",
    "WorkPacket",
    "WorkQueue",
    "WorkQueueError",
    "WorkReceipt",
    "WorkStatus",
    "audit_work_queue",
    "build_work_queue",
]

_RUN_ID = re.compile(r"^run:[a-z0-9]{16,64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PACKET_ID = re.compile(r"^packet:sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# The host may submit a bounded proposal tuple for one packet.  This mirrors
# the specialist proposal ceiling and prevents an oversized response from
# becoming an unbounded input to reconciliation.
MAX_PROPOSALS_PER_PACKET = 24

# One initial response plus one bounded retry is the complete work protocol.
# The value is part of every packet's canonical identity so changing the
# retry contract cannot make an old packet appear current.
MAX_ATTEMPTS_PER_PACKET = 2


class AnalysisMode(StrEnum):
    """Closed analysis modes exposed by the diagnosis protocol."""

    INVENTORY_ONLY = "inventory-only"
    GUIDED = "guided-analysis"


class WorkStatus(StrEnum):
    """Bounded outcome vocabulary for one issued packet."""

    PENDING = "pending"
    COMPLETED = "completed"
    INSUFFICIENT = "insufficient"
    UNRESOLVED = "unresolved"


class WorkQueueError(ValueError):
    """A packet or receipt cannot be reconciled with this queue."""


# Keep this tuple as the single ordering authority for normal specialist work.
# The sceptical reconciler is deliberately excluded: it is appended as a
# locked packet after every normal role.
NORMAL_ROLES = (
    SpecialistRole.TOOLS_AND_INTEGRATIONS,
    SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
    SpecialistRole.PEOPLE_AND_WORK_CONTINUITY,
    SpecialistRole.OPERATING_RHYTHM_AND_MEMORY,
    SpecialistRole.STRENGTH_AND_RECIPROCAL,
    SpecialistRole.RELEASE_DISTANCE,
    SpecialistRole.CONTRADICTIONS_AND_RELIABILITY,
    SpecialistRole.WORKFLOW_SYNTHESIS,
)

_ROLE_QUESTIONS: dict[SpecialistRole, str] = {
    SpecialistRole.TOOLS_AND_INTEGRATIONS: (
        "Which approved tools, integrations, and provider connections are present, "
        "and what useful work do they support?"
    ),
    SpecialistRole.AUTOMATIONS_AND_LIVE_STATE: (
        "What automations and health signals are configured, running, and producing "
        "a proved outcome?"
    ),
    SpecialistRole.PEOPLE_AND_WORK_CONTINUITY: (
        "How do people, meetings, commitments, and follow-through remain connected "
        "over time?"
    ),
    SpecialistRole.OPERATING_RHYTHM_AND_MEMORY: (
        "What planning, review, decision, and durable-memory practices preserve "
        "continuity across sessions?"
    ),
    SpecialistRole.STRENGTH_AND_RECIPROCAL: (
        "Which distinctive methods are especially strong, and what transferable "
        "lesson could Dex learn?"
    ),
    SpecialistRole.RELEASE_DISTANCE: (
        "Which released Dex capabilities are materially newer than a proved local "
        "lineage, without treating held work as available?"
    ),
    SpecialistRole.CONTRADICTIONS_AND_RELIABILITY: (
        "Where do written intent, configuration, runtime, health, or outcomes "
        "contradict one another?"
    ),
    SpecialistRole.WORKFLOW_SYNTHESIS: (
        "Which meaningful cross-surface workflows and missing links emerge from "
        "the approved evidence?"
    ),
    SpecialistRole.SCEPTICAL_RECONCILER: (
        "Which accepted strengths, lessons, surprises, and recommendations survive "
        "a final evidence and contradiction check?"
    ),
}

_FINAL_STATUSES = frozenset(
    {
        WorkStatus.COMPLETED,
        WorkStatus.INSUFFICIENT,
        WorkStatus.UNRESOLVED,
    }
)


def _bounded_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if _ID.fullmatch(value) is None:
            raise ValueError(f"{label} must be bounded identities")
    return tuple(sorted(values))


def _bounded_tokens(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if not value.strip() or _CONTROL.search(value):
            raise ValueError(f"{label} must be bounded non-empty tokens")
    return tuple(sorted(values))


class WorkPacket(_ValidatedInventoried):
    """One immutable engine-issued specialist assignment."""

    packet_id: str = Field(pattern=_PACKET_ID.pattern)
    packet_digest: str = Field(pattern=_SHA256.pattern)
    role: SpecialistRole
    run_id: str = Field(pattern=_RUN_ID.pattern)
    fingerprint_digest: str = Field(pattern=_SHA256.pattern)
    catalogue_digest: str = Field(pattern=_SHA256.pattern)
    evidence_ids: tuple[str, ...]
    catalogue_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    family_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    question: str = Field(min_length=1, max_length=600)
    max_attempts: Literal[2] = MAX_ATTEMPTS_PER_PACKET
    max_proposals: int = Field(ge=0, le=MAX_PROPOSALS_PER_PACKET)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_tokens(values, "packet evidence tokens")

    @field_validator("catalogue_ids")
    @classmethod
    def _catalogue_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_ids(values, "packet catalogue identities")

    @field_validator("capability_ids")
    @classmethod
    def _capability_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_ids(values, "packet capability identities")

    @field_validator("observation_ids")
    @classmethod
    def _observation_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_ids(values, "packet observation identities")

    @field_validator("family_ids")
    @classmethod
    def _family_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_ids(values, "packet family identities")

    @field_validator("workflow_ids")
    @classmethod
    def _workflow_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _bounded_ids(values, "packet workflow identities")

    @field_validator("question")
    @classmethod
    def _question_is_one_safe_line(cls, value: str) -> str:
        if not value.strip() or _CONTROL.search(value):
            raise ValueError("a work packet question must be one bounded line")
        return value

    def canonical_payload(self) -> dict[str, object]:
        """Return the exact content bound by ``packet_digest``."""

        return {
            "catalogue_digest": self.catalogue_digest,
            "catalogue_ids": list(self.catalogue_ids),
            "capability_ids": list(self.capability_ids),
            "evidence_ids": list(self.evidence_ids),
            "family_ids": list(self.family_ids),
            "fingerprint_digest": self.fingerprint_digest,
            "max_attempts": self.max_attempts,
            "max_proposals": self.max_proposals,
            "observation_ids": list(self.observation_ids),
            "question": self.question,
            "role": self.role.value,
            "run_id": self.run_id,
            "workflow_ids": list(self.workflow_ids),
        }

    @model_validator(mode="after")
    def _digest_binds_packet_content(self) -> Self:
        expected = canonical_json_digest(self.canonical_payload())
        if self.packet_digest != expected:
            raise ValueError("packet_digest must bind the exact work packet content")
        if self.packet_id != f"packet:{expected}":
            raise ValueError("packet_id must bind the exact work packet digest")
        return self


class WorkReceipt(_ValidatedInventoried):
    """One immutable response receipt for an issued packet."""

    packet_id: str = Field(pattern=_PACKET_ID.pattern)
    packet_digest: str = Field(pattern=_SHA256.pattern)
    response_digest: str = Field(pattern=_SHA256.pattern)
    status: WorkStatus
    submission_route: Literal["engine-work-packet"] = "engine-work-packet"
    attempt_count: int = Field(ge=1, le=MAX_ATTEMPTS_PER_PACKET)
    proposal_count: int = Field(ge=0, le=MAX_PROPOSALS_PER_PACKET)

    @model_validator(mode="after")
    def _attempt_status_is_bounded(self) -> Self:
        if self.status is WorkStatus.PENDING:
            if self.attempt_count != 1:
                raise ValueError("a pending work receipt must be the first attempt")
            if self.proposal_count != 0:
                raise ValueError("a pending work receipt cannot carry proposals")
        elif self.attempt_count not in (1, MAX_ATTEMPTS_PER_PACKET):
            raise ValueError("a final work receipt must use attempt one or two")
        return self


class WorkQueue(_ValidatedInventoried):
    """Immutable packet state with normal-first and sceptical gating."""

    mode: AnalysisMode
    packets: tuple[WorkPacket, ...]
    receipts: tuple[WorkReceipt, ...] = ()
    sceptical_packet_id: str | None = Field(default=None, pattern=_PACKET_ID.pattern)

    @model_validator(mode="after")
    def _queue_references_are_valid(self) -> Self:
        packet_ids = tuple(item.packet_id for item in self.packets)
        if len(set(packet_ids)) != len(packet_ids):
            raise ValueError("work packet identities must be unique")
        expected_roles = (*NORMAL_ROLES, SpecialistRole.SCEPTICAL_RECONCILER)
        if self.mode is AnalysisMode.INVENTORY_ONLY:
            if self.packets or self.receipts or self.sceptical_packet_id is not None:
                raise ValueError("inventory-only work queue must contain no packets")
            return self
        if tuple(item.role for item in self.packets) != expected_roles:
            raise ValueError(
                "guided work queue must contain the exact normal roles followed by "
                "one sceptical packet"
            )
        if self.sceptical_packet_id != self.packets[-1].packet_id:
            raise ValueError("guided work queue sceptical packet ID is incorrect")
        receipt_ids = tuple(item.packet_id for item in self.receipts)
        if len(set(receipt_ids)) != len(receipt_ids):
            raise ValueError("work receipts must be unique per packet")
        packets_by_id = {item.packet_id: item for item in self.packets}
        for receipt in self.receipts:
            packet = packets_by_id.get(receipt.packet_id)
            if packet is None:
                raise ValueError("work receipt references a packet outside this queue")
            if receipt.packet_digest != packet.packet_digest:
                raise ValueError("work receipt packet digest does not match issued work")
            if receipt.proposal_count > packet.max_proposals:
                raise ValueError("work receipt exceeds the packet proposal limit")
        final_ids = {
            receipt.packet_id for receipt in self.receipts if receipt.status in _FINAL_STATUSES
        }
        normal_ids = {
            packet.packet_id
            for packet in self.packets
            if packet.role is not SpecialistRole.SCEPTICAL_RECONCILER
        }
        receipt_ids_set = set(receipt_ids)
        if self.sceptical_packet_id in receipt_ids_set and not normal_ids <= final_ids:
            raise ValueError("sceptical receipt requires final normal receipts")
        return self

    def pending_packets(self) -> tuple[WorkPacket, ...]:
        """Return legal next packets, keeping sceptical work locked."""

        completed = {
            item.packet_id for item in self.receipts if item.status in _FINAL_STATUSES
        }
        normal = tuple(
            item
            for item in self.packets
            if item.packet_id not in completed
            and item.role is not SpecialistRole.SCEPTICAL_RECONCILER
        )
        if normal:
            return normal
        return tuple(item for item in self.packets if item.packet_id not in completed)

    def complete(self) -> bool:
        """Whether every issued packet has an explicit receipt."""

        return not self.pending_packets()

    def require_pending(self, packet_id: str) -> WorkPacket:
        """Return one legal packet or fail closed for stale/locked input."""

        matches = tuple(item for item in self.packets if item.packet_id == packet_id)
        if len(matches) != 1:
            raise WorkQueueError("packet is not in this work queue")
        existing = tuple(item for item in self.receipts if item.packet_id == packet_id)
        if existing and existing[0].status in _FINAL_STATUSES:
            raise WorkQueueError("packet already has a response")
        packet = matches[0]
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER and any(
            item.role is not SpecialistRole.SCEPTICAL_RECONCILER
            and item.packet_id
            not in {
                receipt.packet_id
                for receipt in self.receipts
                if receipt.status in _FINAL_STATUSES
            }
            for item in self.packets
        ):
            raise WorkQueueError("sceptical packet is locked until normal work is complete")
        return packet

    def record(self, receipt: WorkReceipt) -> WorkQueue:
        """Record a response, treating an identical replay as a no-op."""

        existing = tuple(item for item in self.receipts if item.packet_id == receipt.packet_id)
        if existing:
            if existing == (receipt,):
                return self
            previous = existing[0]
            if (
                previous.status is WorkStatus.PENDING
                and previous.attempt_count == 1
                and receipt.status in _FINAL_STATUSES
                and receipt.attempt_count == MAX_ATTEMPTS_PER_PACKET
            ):
                packet = self.require_pending(receipt.packet_id)
                if receipt.packet_digest != packet.packet_digest:
                    raise WorkQueueError("response packet digest does not match issued work")
                if receipt.proposal_count > packet.max_proposals:
                    raise WorkQueueError("response exceeds the packet proposal limit")
                replaced = tuple(
                    receipt if item.packet_id == receipt.packet_id else item
                    for item in self.receipts
                )
                return self.model_copy(update={"receipts": replaced})
            raise WorkQueueError("packet already has a different response")
        if receipt.status in _FINAL_STATUSES and receipt.attempt_count != 1:
            raise WorkQueueError("a first final response must use attempt one")
        packet = self.require_pending(receipt.packet_id)
        if receipt.packet_digest != packet.packet_digest:
            raise WorkQueueError("response packet digest does not match issued work")
        if receipt.proposal_count > packet.max_proposals:
            raise WorkQueueError("response exceeds the packet proposal limit")
        return self.model_copy(update={"receipts": (*self.receipts, receipt)})

    def audit(self) -> WorkAudit:
        """Build the immutable audit summary used by later run checkpoints."""

        return WorkAudit(
            mode=self.mode,
            packet_count=len(self.packets),
            completed_count=sum(
                1 for receipt in self.receipts if receipt.status in _FINAL_STATUSES
            ),
            unresolved_count=sum(
                1
                for receipt in self.receipts
                if receipt.status is WorkStatus.UNRESOLVED
                and receipt.status in _FINAL_STATUSES
            ),
            manual_submission_count=sum(
                1
                for receipt in self.receipts
                if receipt.submission_route != "engine-work-packet"
            ),
            receipts=self.receipts,
        )


class WorkAudit(_ValidatedInventoried):
    """Bounded reconciliation facts retained for a diagnosis run."""

    mode: AnalysisMode
    packet_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    manual_submission_count: int = Field(ge=0)
    receipts: tuple[WorkReceipt, ...]

    @model_validator(mode="after")
    def _audit_counts_match_receipts(self) -> Self:
        expected_packet_count = (
            0
            if self.mode is AnalysisMode.INVENTORY_ONLY
            else len(NORMAL_ROLES) + 1
        )
        if self.packet_count != expected_packet_count:
            raise ValueError("packet_count must match the queue mode")
        receipt_ids = tuple(receipt.packet_id for receipt in self.receipts)
        if len(set(receipt_ids)) != len(receipt_ids):
            raise ValueError("receipts must be unique per packet")
        if len(self.receipts) > self.packet_count:
            raise ValueError("receipts cannot exceed packet_count")
        if self.mode is AnalysisMode.INVENTORY_ONLY and self.receipts:
            raise ValueError("inventory-only audits must contain no receipts")
        expected_completed = sum(
            1 for receipt in self.receipts if receipt.status in _FINAL_STATUSES
        )
        expected_unresolved = sum(
            1
            for receipt in self.receipts
            if receipt.status is WorkStatus.UNRESOLVED
        )
        expected_manual = sum(
            1
            for receipt in self.receipts
            if receipt.submission_route != "engine-work-packet"
        )
        if self.completed_count != expected_completed:
            raise ValueError("completed_count must match final receipts")
        if self.unresolved_count != expected_unresolved:
            raise ValueError("unresolved_count must match unresolved receipts")
        if self.manual_submission_count != expected_manual:
            raise ValueError("manual_submission_count must match receipts")
        return self


def audit_work_queue(queue: WorkQueue) -> WorkAudit:
    """Functional alias for callers that prefer a free function."""

    return queue.audit()


def _context_value(context: object, name: str, default: Sequence[str] = ()) -> object:
    if isinstance(context, Mapping):
        return context.get(name, default)
    return getattr(context, name, default)


def _context_tuple(context: object, name: str) -> tuple[str, ...]:
    value = _context_value(context, name)
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)  # type: ignore[arg-type]


def _packet_for_role(
    role: SpecialistRole,
    *,
    context: object,
) -> WorkPacket:
    """Issue one packet whose digest covers every allowed identity."""

    values: dict[str, Any] = {
        "role": role,
        "run_id": _context_value(context, "run_id", ""),
        "fingerprint_digest": _context_value(context, "fingerprint_digest", ""),
        "catalogue_digest": _context_value(context, "catalogue_digest", ""),
        "evidence_ids": _context_tuple(context, "evidence_ids"),
        "catalogue_ids": _context_tuple(context, "catalogue_ids"),
        "capability_ids": _context_tuple(context, "capability_ids"),
        "observation_ids": _context_tuple(context, "observation_ids"),
        "family_ids": _context_tuple(context, "family_ids"),
        "workflow_ids": _context_tuple(context, "workflow_ids"),
        "question": _ROLE_QUESTIONS[role],
        "max_attempts": MAX_ATTEMPTS_PER_PACKET,
        "max_proposals": MAX_PROPOSALS_PER_PACKET,
    }
    # Canonicalise every allowed identity before minting the content-bound
    # digest.  This makes equivalent contexts independent of input ordering.
    for field_name in (
        "evidence_ids",
        "catalogue_ids",
        "capability_ids",
        "observation_ids",
        "family_ids",
        "workflow_ids",
    ):
        values[field_name] = tuple(sorted(values[field_name]))
    payload = {
        "catalogue_digest": values["catalogue_digest"],
        "catalogue_ids": list(values["catalogue_ids"]),
        "capability_ids": list(values["capability_ids"]),
        "evidence_ids": list(values["evidence_ids"]),
        "family_ids": list(values["family_ids"]),
        "fingerprint_digest": values["fingerprint_digest"],
        "max_attempts": values["max_attempts"],
        "max_proposals": values["max_proposals"],
        "observation_ids": list(values["observation_ids"]),
        "question": values["question"],
        "role": role.value,
        "run_id": values["run_id"],
        "workflow_ids": list(values["workflow_ids"]),
    }
    digest = canonical_json_digest(payload)
    return WorkPacket(
        packet_id=f"packet:{digest}",
        packet_digest=digest,
        **values,
    )


def build_work_queue(*, context: object, mode: AnalysisMode) -> WorkQueue:
    """Build the deterministic queue for one proposal context and mode."""

    analysis_mode = AnalysisMode(mode)
    if analysis_mode is AnalysisMode.INVENTORY_ONLY:
        return WorkQueue(mode=analysis_mode, packets=())

    packets = tuple(_packet_for_role(role, context=context) for role in NORMAL_ROLES)
    sceptical = _packet_for_role(SpecialistRole.SCEPTICAL_RECONCILER, context=context)
    return WorkQueue(
        mode=analysis_mode,
        packets=(*packets, sceptical),
        sceptical_packet_id=sceptical.packet_id,
    )
