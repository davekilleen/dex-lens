"""Host-neutral, fail-closed adaptation contracts (HANDOFF M4/G3).

The package surface is lazy by design.  Adapter contracts import the small
``adaptation.contract`` module during their own initialization; eagerly
importing transactions and verification here would pull diagnosis back into a
partially initialized adapter package.
"""

from __future__ import annotations

from importlib import import_module

_MODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "allowlist": (
        "ALLOWED_OPERATIONS",
        "AllowedOperation",
        "OperationAssessment",
        "OperationRequest",
        "RefusalCode",
        "assess_operation",
        "canonical_target",
    ),
    "approval": (
        "AdaptationApproval",
        "ApprovalAuthority",
        "ApprovalExpiredError",
        "ApprovalMismatchError",
        "ApprovalReplayError",
        "IssuedApproval",
    ),
    "contract": (
        "REQUIRED_GUARANTEES",
        "Guarantee",
        "MutationContract",
        "OperationKind",
    ),
    "incidents": ("IncidentKind", "IncidentRecord"),
    "preview": (
        "AdaptationPreview",
        "PreviewDriftError",
        "PreviewMismatchError",
        "assert_preview_current",
        "build_preview",
    ),
    "receipt": ("TransactionReceipt", "read_receipt", "write_receipt"),
    "recovery": (
        "RecoveryConflictError",
        "RecoveryPoint",
        "RecoveryUnavailableError",
        "create_recovery_point",
        "restore_absent_target",
        "validate_recovery_point",
    ),
    "transaction": (
        "AutomationHardStoppedError",
        "InjectedCrash",
        "JournalState",
        "RecoveryFailedError",
        "TransactionConflictError",
        "TransactionEngine",
        "TransactionFailedError",
        "TransactionJournal",
        "TransactionResult",
        "UndoConflictError",
        "UndoResult",
        "UndoStatus",
    ),
    "verification": (
        "CREATED_SKILL_OUTCOME_SIGNAL",
        "OutcomeCheck",
        "OutcomeCheckState",
        "OutcomeObservationArtifact",
        "VerificationResult",
        "VerificationVerdict",
        "has_outcome_procedure",
        "verify_created_skill",
    ),
}

_EXPORT_MODULE = {
    export: f"capability_exchange.adaptation.{module}"
    for module, exports in _MODULE_EXPORTS.items()
    for export in exports
}

__all__ = sorted(_EXPORT_MODULE)


def __getattr__(name: str) -> object:
    """Load a public adaptation symbol only when a caller requests it."""

    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
