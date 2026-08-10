from __future__ import annotations

import pytest
from pydantic import ValidationError

from capability_exchange.adaptation.contract import (
    REQUIRED_GUARANTEES,
    Guarantee,
    MutationContract,
    OperationKind,
)
from capability_exchange.boundary.serialization import InventoriedModel


def valid_contract(**overrides: object) -> MutationContract:
    values: dict[str, object] = {
        "contract_id": "claude-code-local-mutation",
        "contract_version": "1.0.0",
        "operations": (OperationKind.CREATE_NAMESPACED_SKILL,),
        "guarantees": REQUIRED_GUARANTEES,
    }
    values.update(overrides)
    return MutationContract(**values)


def test_contract_is_closed_to_the_one_registered_operation() -> None:
    contract = valid_contract()
    assert contract.operations == (OperationKind.CREATE_NAMESPACED_SKILL,)
    with pytest.raises(ValidationError):
        valid_contract(operations=("send-message",))


def test_fresh_permission_is_a_required_guarantee_not_an_implementation_detail() -> None:
    assert Guarantee.PERMISSION in REQUIRED_GUARANTEES


def test_contract_fields_are_inside_the_g2_inventory_boundary() -> None:
    assert issubclass(MutationContract, InventoriedModel)
    payload = valid_contract().model_dump(mode="json")
    assert payload["contract_id"] == "claude-code-local-mutation"


@pytest.mark.parametrize("missing", list(Guarantee))
def test_adapt_capability_requires_every_guarantee(missing: Guarantee) -> None:
    incomplete = tuple(item for item in REQUIRED_GUARANTEES if item is not missing)
    with pytest.raises(ValidationError, match=missing.value):
        valid_contract(guarantees=incomplete)


def test_duplicate_operations_and_guarantees_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        valid_contract(
            operations=(
                OperationKind.CREATE_NAMESPACED_SKILL,
                OperationKind.CREATE_NAMESPACED_SKILL,
            )
        )
    with pytest.raises(ValidationError, match="duplicate"):
        valid_contract(guarantees=REQUIRED_GUARANTEES + (Guarantee.UNDO,))


def test_contract_is_frozen_and_forbids_extra_fields() -> None:
    contract = valid_contract()
    with pytest.raises(ValidationError):
        contract.contract_version = "2.0.0"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        MutationContract(
            contract_id="claude-code-local-mutation",
            contract_version="1.0.0",
            operations=(OperationKind.CREATE_NAMESPACED_SKILL,),
            guarantees=REQUIRED_GUARANTEES,
            shell_command="rm -rf something",  # type: ignore[call-arg]
        )
