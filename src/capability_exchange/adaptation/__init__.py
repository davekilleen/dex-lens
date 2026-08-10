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
from capability_exchange.adaptation.approval import (
    AdaptationApproval,
    ApprovalAuthority,
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalReplayError,
    IssuedApproval,
)
from capability_exchange.adaptation.contract import (
    REQUIRED_GUARANTEES,
    Guarantee,
    MutationContract,
    OperationKind,
)
from capability_exchange.adaptation.preview import (
    AdaptationPreview,
    PreviewDriftError,
    PreviewMismatchError,
    assert_preview_current,
    build_preview,
)

__all__ = [
    "ALLOWED_OPERATIONS",
    "REQUIRED_GUARANTEES",
    "AllowedOperation",
    "AdaptationApproval",
    "AdaptationPreview",
    "ApprovalAuthority",
    "ApprovalExpiredError",
    "ApprovalMismatchError",
    "ApprovalReplayError",
    "Guarantee",
    "MutationContract",
    "OperationAssessment",
    "OperationKind",
    "OperationRequest",
    "IssuedApproval",
    "PreviewDriftError",
    "PreviewMismatchError",
    "RefusalCode",
    "assess_operation",
    "assert_preview_current",
    "build_preview",
    "canonical_target",
]
