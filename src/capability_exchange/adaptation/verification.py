"""Core-owned, Success-Contract-scoped M4 outcome verification (T7)."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.preview import AdaptationPreview
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.finding import CapabilityState
from capability_exchange.evidence import EvidenceLevel, EvidenceState, evidence_level
from capability_exchange.evidence.item import reference_rejection_reason
from capability_exchange.jobs.contract import SuccessContract

__all__ = [
    "CREATED_SKILL_OUTCOME_SIGNAL",
    "OutcomeCheck",
    "OutcomeCheckState",
    "OutcomeObservationArtifact",
    "VerificationResult",
    "VerificationVerdict",
    "has_outcome_procedure",
    "verify_created_skill",
]


CREATED_SKILL_OUTCOME_SIGNAL = (
    "The approved skill is loadable Markdown with the exact previewed bytes"
)
_PROCEDURE_ID = "create-namespaced-skill-loadability-v1"


class VerificationVerdict(StrEnum):
    WORKING = "working"
    PARTIAL = "partial"
    NOT_DEMONSTRATED = "not-demonstrated"
    UNKNOWN = "unknown"


class OutcomeCheckState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class OutcomeCheck(InventoriedModel):
    """One core-observed check; it deliberately contains no caller verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    state: OutcomeCheckState
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OutcomeObservationArtifact(InventoriedModel):
    """Canonical evidence emitted and reread by the core-owned procedure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    procedure_id: Literal["create-namespaced-skill-loadability-v1"] = _PROCEDURE_ID
    operation: Literal[OperationKind.CREATE_NAMESPACED_SKILL]
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observable_signal: Literal[
        "The approved skill is loadable Markdown with the exact previewed bytes"
    ]
    checks: tuple[OutcomeCheck, ...] = Field(min_length=2, max_length=2)
    started_at: datetime
    completed_at: datetime

    @field_validator("started_at", "completed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("outcome procedure times must be timezone-aware")
        return value


class VerificationResult(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: VerificationVerdict
    capability_state: CapabilityState
    evidence_state: EvidenceState
    evidence_level: EvidenceLevel
    observable_signal: str
    procedure_id: str | None = None
    evidence_reference: str | None = None
    evidence_sha256: str | None = None
    contract_digest: str | None = None
    detail: str
    verified_at: datetime

    @field_validator("verified_at")
    @classmethod
    def _verified_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware")
        return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _contract_digest(contract: SuccessContract) -> str:
    return _sha256(_canonical(contract.model_dump(mode="json")))


def _result(
    *,
    verdict: VerificationVerdict,
    capability_state: CapabilityState,
    evidence_state: EvidenceState,
    observable_signal: str,
    detail: str,
    verified_at: datetime,
    procedure_id: str | None = None,
    evidence_reference: str | None = None,
    evidence_sha256: str | None = None,
    contract_digest: str | None = None,
) -> VerificationResult:
    return VerificationResult(
        verdict=verdict,
        capability_state=capability_state,
        evidence_state=evidence_state,
        evidence_level=evidence_level((evidence_state,)),
        observable_signal=observable_signal,
        procedure_id=procedure_id,
        evidence_reference=evidence_reference,
        evidence_sha256=evidence_sha256,
        contract_digest=contract_digest,
        detail=detail,
        verified_at=verified_at,
    )


def has_outcome_procedure(operation: OperationKind, observable_signal: str) -> bool:
    """Real-user create-skill outcomes need later-use evidence; none is supported yet."""

    del operation, observable_signal
    return False


def _is_isolated_recovery_drill(
    preview: AdaptationPreview, contract: SuccessContract, observable_signal: str
) -> bool:
    """Permit only the fixed synthetic transaction used to exercise recovery."""

    root = Path(preview.approved_root)
    return (
        preview.host_id == "synthetic-recovery-drill"
        and preview.job_id == contract.job_id == "recovery-drill"
        and preview.capability_id == "recovery-proof"
        and preview.relative_path == "dex-lens-recovery-drill.md"
        and observable_signal == CREATED_SKILL_OUTCOME_SIGNAL
        and any(part.startswith("dex-pilot-recovery-") for part in root.parts)
    )


def _run_created_skill_procedure(
    preview: AdaptationPreview,
    contract: SuccessContract,
    observable_signal: str,
    verified_at: datetime,
) -> OutcomeObservationArtifact:
    target = Path(preview.target_path)
    try:
        content = target.read_bytes()
        exact_state = (
            OutcomeCheckState.PASSED
            if _sha256(content) == preview.content_sha256
            else OutcomeCheckState.FAILED
        )
        try:
            text = content.decode("utf-8")
            markdown_state = (
                OutcomeCheckState.PASSED
                if text.startswith("# ")
                else OutcomeCheckState.FAILED
            )
        except UnicodeDecodeError:
            markdown_state = OutcomeCheckState.FAILED
    except OSError:
        exact_state = OutcomeCheckState.UNAVAILABLE
        markdown_state = OutcomeCheckState.UNAVAILABLE
    checks = (
        OutcomeCheck(
            check_id="exact-preview-bytes",
            state=exact_state,
            observation_sha256=_sha256(
                _canonical({"target": preview.target_path, "state": exact_state.value})
            ),
        ),
        OutcomeCheck(
            check_id="loadable-markdown-heading",
            state=markdown_state,
            observation_sha256=_sha256(
                _canonical({"target": preview.target_path, "state": markdown_state.value})
            ),
        ),
    )
    return OutcomeObservationArtifact(
        operation=preview.operation,
        preview_digest=preview.preview_digest,
        contract_digest=_contract_digest(contract),
        observable_signal=observable_signal,
        checks=checks,
        started_at=verified_at,
        completed_at=verified_at,
    )


def _persist_and_reread(
    artifact: OutcomeObservationArtifact, evidence_root: Path
) -> tuple[OutcomeObservationArtifact, Path, str]:
    evidence_root.mkdir(parents=True, exist_ok=True)
    path = evidence_root / f"outcome-{artifact.preview_digest}.json"
    encoded = _canonical(artifact.dump_for_storage())
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    reread = path.read_bytes()
    parsed = OutcomeObservationArtifact.model_validate_json(reread)
    if parsed != artifact:
        raise ValueError("outcome evidence read-back differs from observed checks")
    return parsed, path, _sha256(reread)


def verify_created_skill(
    preview: AdaptationPreview,
    contract: SuccessContract,
    *,
    observable_signal: str,
    verified_at: datetime,
    evidence_root: Path | None = None,
) -> VerificationResult:
    """Run the core-owned procedure, reread its evidence, then derive the verdict."""

    contract_hash = _contract_digest(contract)
    if contract.job_id != preview.job_id or observable_signal not in contract.success_evidence:
        return _result(
            verdict=VerificationVerdict.NOT_DEMONSTRATED,
            capability_state=CapabilityState.NOT_DEMONSTRATED,
            evidence_state=EvidenceState.INSUFFICIENT,
            observable_signal=observable_signal,
            detail="observable signal is not declared by the exact confirmed Success Contract",
            verified_at=verified_at,
            contract_digest=contract_hash,
        )
    if not _is_isolated_recovery_drill(preview, contract, observable_signal):
        return _result(
            verdict=VerificationVerdict.UNKNOWN,
            capability_state=CapabilityState.UNKNOWN,
            evidence_state=EvidenceState.UNVERIFIED,
            observable_signal=observable_signal,
            detail=(
                "configuration presence is not proof that the person's job improved; "
                "no real-user outcome procedure supports this exact signal"
            ),
            verified_at=verified_at,
            contract_digest=contract_hash,
        )
    if evidence_root is None:
        return _result(
            verdict=VerificationVerdict.UNKNOWN,
            capability_state=CapabilityState.UNKNOWN,
            evidence_state=EvidenceState.UNVERIFIED,
            observable_signal=observable_signal,
            detail="no outcome evidence root is available",
            verified_at=verified_at,
            contract_digest=contract_hash,
        )
    try:
        observed = _run_created_skill_procedure(
            preview, contract, observable_signal, verified_at
        )
        proof, path, proof_hash = _persist_and_reread(observed, evidence_root)
        if (
            proof.preview_digest != preview.preview_digest
            or proof.contract_digest != contract_hash
            or proof.observable_signal != observable_signal
            or proof.operation is not preview.operation
            or tuple(check.check_id for check in proof.checks)
            != ("exact-preview-bytes", "loadable-markdown-heading")
        ):
            raise ValueError("outcome evidence bindings are invalid")
    except Exception:  # noqa: BLE001 - evidence failure must become Unknown
        return _result(
            verdict=VerificationVerdict.UNKNOWN,
            capability_state=CapabilityState.UNKNOWN,
            evidence_state=EvidenceState.UNVERIFIED,
            observable_signal=observable_signal,
            detail="outcome procedure or evidence verification failed",
            verified_at=verified_at,
            contract_digest=contract_hash,
        )
    states = tuple(check.state for check in proof.checks)
    if OutcomeCheckState.UNAVAILABLE in states:
        verdict = VerificationVerdict.UNKNOWN
    elif all(state is OutcomeCheckState.PASSED for state in states):
        verdict = VerificationVerdict.WORKING
    elif any(state is OutcomeCheckState.PASSED for state in states):
        verdict = VerificationVerdict.PARTIAL
    else:
        verdict = VerificationVerdict.NOT_DEMONSTRATED
    mapping = {
        VerificationVerdict.WORKING: (CapabilityState.WORKING, EvidenceState.OBSERVED),
        VerificationVerdict.PARTIAL: (CapabilityState.PARTIAL, EvidenceState.OBSERVED),
        VerificationVerdict.NOT_DEMONSTRATED: (
            CapabilityState.NOT_DEMONSTRATED,
            EvidenceState.INSUFFICIENT,
        ),
        VerificationVerdict.UNKNOWN: (CapabilityState.UNKNOWN, EvidenceState.UNVERIFIED),
    }
    capability_state, evidence_state = mapping[verdict]
    reference = str(path)
    if reference_rejection_reason(reference) is not None:
        raise ValueError("outcome evidence reference is not a safe locator")
    return _result(
        verdict=verdict,
        capability_state=capability_state,
        evidence_state=evidence_state,
        observable_signal=observable_signal,
        procedure_id=proof.procedure_id,
        evidence_reference=reference,
        evidence_sha256=proof_hash,
        contract_digest=contract_hash,
        detail="verdict derived from the reread core-owned outcome evidence artifact",
        verified_at=verified_at,
    )
