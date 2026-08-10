from __future__ import annotations

import pytest

from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.eligibility import (
    EligibilityReason,
    adaptation_eligibility,
)


@pytest.mark.parametrize(
    ("proposal", "operation", "reason"),
    (
        (
            "Email the result to my manager every Friday",
            OperationKind.CREATE_NAMESPACED_SKILL,
            EligibilityReason.HIGH_IMPACT_PROPOSAL,
        ),
        (
            "Create a local topic grouping helper",
            "send-message",
            EligibilityReason.NOT_ALLOWLISTED,
        ),
        (
            object(),
            OperationKind.CREATE_NAMESPACED_SKILL,
            EligibilityReason.HIGH_IMPACT_PROPOSAL,
        ),
    ),
)
def test_g6_and_g3_each_independently_refuse_hostile_adaptation(
    proposal: object,
    operation: object,
    reason: EligibilityReason,
) -> None:
    decision = adaptation_eligibility(
        job_description="Keep my reading list organized by topic",
        contract_fields={},
        proposal_description=proposal,
        operation=operation,
    )
    assert not decision.allowed
    assert decision.reason is reason


def test_unknown_operation_has_no_constructable_enum_member() -> None:
    with pytest.raises(ValueError):
        OperationKind("delete-user-files")
