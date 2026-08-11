from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.eligibility import EligibilityReason, adaptation_eligibility


def test_g6_blocks_high_impact_proposal_even_when_operation_kind_is_allowlisted() -> None:
    decision = adaptation_eligibility(
        job_description="Keep my reading list organized by topic",
        contract_fields={},
        proposal_description="Email the organized list every Friday",
        operation=OperationKind.CREATE_NAMESPACED_SKILL,
    )
    assert not decision.allowed
    assert decision.reason is EligibilityReason.HIGH_IMPACT_PROPOSAL


def test_g3_blocks_non_allowlisted_operation_even_when_taxonomy_is_benign() -> None:
    decision = adaptation_eligibility(
        job_description="Keep my reading list organized by topic",
        contract_fields={},
        proposal_description="Create a local topic grouping helper",
        operation="send-message",
    )
    assert not decision.allowed
    assert decision.reason is EligibilityReason.NOT_ALLOWLISTED


def test_both_independent_layers_must_pass() -> None:
    decision = adaptation_eligibility(
        job_description="Keep my reading list organized by topic",
        contract_fields={},
        proposal_description="Create a local topic grouping helper",
        operation=OperationKind.CREATE_NAMESPACED_SKILL,
    )
    assert decision.allowed
    assert decision.reason is EligibilityReason.ALLOWED

