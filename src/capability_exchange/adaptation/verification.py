"""Success-Contract-scoped M4 outcome verification (T7)."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import ConfigDict, field_validator

from capability_exchange.adaptation.preview import AdaptationPreview
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.finding import CapabilityState
from capability_exchange.evidence import EvidenceLevel, EvidenceState, evidence_level
from capability_exchange.jobs.contract import SuccessContract

__all__ = ["VerificationResult", "VerificationVerdict", "verify_created_skill"]


class VerificationVerdict(StrEnum):
    WORKING = "working"
    PARTIAL = "partial"
    NOT_DEMONSTRATED = "not-demonstrated"
    UNKNOWN = "unknown"


class VerificationResult(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: VerificationVerdict
    capability_state: CapabilityState
    evidence_state: EvidenceState
    evidence_level: EvidenceLevel
    observable_signal: str
    detail: str
    verified_at: datetime

    @field_validator("verified_at")
    @classmethod
    def _verified_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware")
        return value


def _result(
    *,
    verdict: VerificationVerdict,
    capability_state: CapabilityState,
    evidence_state: EvidenceState,
    observable_signal: str,
    detail: str,
    verified_at: datetime,
) -> VerificationResult:
    return VerificationResult(
        verdict=verdict,
        capability_state=capability_state,
        evidence_state=evidence_state,
        evidence_level=evidence_level((evidence_state,)),
        observable_signal=observable_signal,
        detail=detail,
        verified_at=verified_at,
    )


def verify_created_skill(
    preview: AdaptationPreview,
    contract: SuccessContract,
    *,
    observable_signal: str,
    verified_at: datetime,
) -> VerificationResult:
    """Verify exact bytes and a signal predeclared by the confirmed contract."""

    if contract.job_id != preview.job_id or observable_signal not in contract.success_evidence:
        return _result(
            verdict=VerificationVerdict.NOT_DEMONSTRATED,
            capability_state=CapabilityState.NOT_DEMONSTRATED,
            evidence_state=EvidenceState.INSUFFICIENT,
            observable_signal=observable_signal,
            detail="observable signal is not declared by the exact confirmed Success Contract",
            verified_at=verified_at,
        )
    target = Path(preview.target_path)
    if not os.path.lexists(target):
        return _result(
            verdict=VerificationVerdict.NOT_DEMONSTRATED,
            capability_state=CapabilityState.NOT_DEMONSTRATED,
            evidence_state=EvidenceState.ABSENT,
            observable_signal=observable_signal,
            detail="the approved target is absent",
            verified_at=verified_at,
        )
    try:
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError:
        return _result(
            verdict=VerificationVerdict.UNKNOWN,
            capability_state=CapabilityState.UNKNOWN,
            evidence_state=EvidenceState.UNVERIFIED,
            observable_signal=observable_signal,
            detail="verifier could not read the approved target; automation must stop",
            verified_at=verified_at,
        )
    if actual != preview.content_sha256:
        return _result(
            verdict=VerificationVerdict.NOT_DEMONSTRATED,
            capability_state=CapabilityState.NOT_DEMONSTRATED,
            evidence_state=EvidenceState.CONFLICTING,
            observable_signal=observable_signal,
            detail="target bytes do not match the exact approved preview",
            verified_at=verified_at,
        )
    return _result(
        verdict=VerificationVerdict.WORKING,
        capability_state=CapabilityState.WORKING,
        evidence_state=EvidenceState.OBSERVED,
        observable_signal=observable_signal,
        detail="exact approved bytes are present and the declared signal is testable",
        verified_at=verified_at,
    )

