"""Independent G6 job/proposal taxonomy and G3 operation allowlist wall."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from capability_exchange.adaptation.allowlist import assess_operation
from capability_exchange.taxonomy.classifier import classify_job, classify_text

__all__ = ["EligibilityDecision", "EligibilityReason", "adaptation_eligibility"]


class EligibilityReason(StrEnum):
    ALLOWED = "allowed"
    HIGH_IMPACT_JOB = "high-impact-job"
    HIGH_IMPACT_PROPOSAL = "high-impact-proposal"
    NOT_ALLOWLISTED = "not-allowlisted"


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    allowed: bool
    reason: EligibilityReason
    explanation: str


def adaptation_eligibility(
    *,
    job_description: object,
    contract_fields: Mapping[str, object] | None,
    proposal_description: object,
    operation: object,
) -> EligibilityDecision:
    """Both layers must independently pass; uncertainty in either refuses."""

    job = classify_job(job_description, contract_fields)
    if job.high_impact:
        return EligibilityDecision(
            allowed=False,
            reason=EligibilityReason.HIGH_IMPACT_JOB,
            explanation="high-impact jobs remain diagnosis-only",
        )
    proposal = classify_text(proposal_description)
    if proposal.high_impact:
        return EligibilityDecision(
            allowed=False,
            reason=EligibilityReason.HIGH_IMPACT_PROPOSAL,
            explanation="the proposed adaptation is high-impact or unclassifiable",
        )
    operation_decision = assess_operation(operation)
    if not operation_decision.allowed:
        return EligibilityDecision(
            allowed=False,
            reason=EligibilityReason.NOT_ALLOWLISTED,
            explanation=operation_decision.explanation,
        )
    return EligibilityDecision(
        allowed=True,
        reason=EligibilityReason.ALLOWED,
        explanation="job, proposal, and closed local operation each passed independently",
    )

