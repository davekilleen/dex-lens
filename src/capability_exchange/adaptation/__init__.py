"""Host-neutral, fail-closed adaptation contracts (HANDOFF M4/G3)."""

from capability_exchange.adaptation.allowlist import (
    ALLOWED_OPERATIONS,
    AllowedOperation,
    OperationAssessment,
    OperationRequest,
    RefusalCode,
    assess_operation,
    canonical_target,
)
from capability_exchange.adaptation.contract import (
    REQUIRED_GUARANTEES,
    Guarantee,
    MutationContract,
    OperationKind,
)

__all__ = [
    "ALLOWED_OPERATIONS",
    "REQUIRED_GUARANTEES",
    "AllowedOperation",
    "Guarantee",
    "MutationContract",
    "OperationAssessment",
    "OperationKind",
    "OperationRequest",
    "RefusalCode",
    "assess_operation",
    "canonical_target",
]

