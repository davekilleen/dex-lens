"""Layered evaluation of discovery, comparison and the human-facing report."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from capability_exchange.diagnosis.comparison import (
    ComparisonLedger,
    Disposition,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    ObservationKind,
    OperationalState,
)
from capability_exchange.reports.store import missing_report_requirements

__all__ = ["EvaluationResult", "evaluate_diagnosis"]


@dataclass(frozen=True)
class EvaluationResult:
    """Failures separated by the layer that needs to improve."""

    observation_errors: tuple[str, ...]
    capability_errors: tuple[str, ...]
    comparison_errors: tuple[str, ...]
    report_errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not (
            self.observation_errors
            or self.capability_errors
            or self.comparison_errors
            or self.report_errors
        )


def _attribute(fingerprint: EvidenceFingerprint, kind: ObservationKind, key: str) -> str | None:
    for observation in fingerprint.observations:
        if observation.kind is not kind:
            continue
        for attribute in observation.attributes:
            if attribute.key == key:
                return attribute.value
    return None


def _count(
    fingerprint: EvidenceFingerprint,
    kind: ObservationKind,
    state: OperationalState | None = None,
) -> int:
    return sum(
        observation.kind is kind
        and (state is None or observation.operational_state is state)
        for observation in fingerprint.observations
    )


def _observation_errors(
    fingerprint: EvidenceFingerprint, expected: Mapping[str, object]
) -> tuple[str, ...]:
    errors: list[str] = []
    expected_release = str(expected.get("release_id", ""))
    if _attribute(fingerprint, ObservationKind.RELEASE, "release-id") != expected_release:
        errors.append(f"release identity should be {expected_release}")

    observations = expected.get("observations", {})
    if not isinstance(observations, Mapping):
        return (*errors, "expected observation contract is malformed")
    checks = {
        "mcp_servers_declared": _count(
            fingerprint, ObservationKind.MCP_SERVER, OperationalState.DECLARED
        ),
        "mcp_tools_known": _count(fingerprint, ObservationKind.MCP_TOOL),
        "automation_implemented": _count(
            fingerprint, ObservationKind.AUTOMATION, OperationalState.IMPLEMENTED
        ),
        "automation_loaded": _count(
            fingerprint, ObservationKind.AUTOMATION, OperationalState.LOADED
        ),
        "health_collectors": _count(fingerprint, ObservationKind.HEALTH_CHECK),
        "restore_proofs": _count(fingerprint, ObservationKind.RECOVERY_PROOF),
    }
    for key, actual in checks.items():
        wanted = observations.get(key)
        if actual != wanted:
            errors.append(f"{key} should be {wanted}, observed {actual}")

    if checks["mcp_servers_declared"] and not checks["mcp_tools_known"]:
        if not any("MCP doorways" in limit for limit in fingerprint.limits):
            errors.append(
                "tool inventory must remain Unknown when servers are configured "
                "but their tools were not safely enumerated"
            )
    return tuple(errors)


def _capability_errors(
    ledger: ComparisonLedger, expected: Mapping[str, object]
) -> tuple[str, ...]:
    required = expected.get("required_capabilities", ())
    required_ids = {str(item) for item in required} if isinstance(required, list) else set()
    actual = {item.capability_id for item in ledger.capabilities}
    return tuple(
        f"missing human capability: {capability_id}"
        for capability_id in sorted(required_ids - actual)
    )


def _comparison_errors(
    ledger: ComparisonLedger, expected: Mapping[str, object]
) -> tuple[str, ...]:
    errors: list[str] = []
    required = expected.get("required_dispositions", {})
    required_map = required if isinstance(required, Mapping) else {}
    by_id = {item.catalogue_id: item for item in ledger.entries}
    for raw_id, raw_disposition in required_map.items():
        catalogue_id = str(raw_id)
        wanted = str(raw_disposition)
        item = by_id.get(catalogue_id)
        if item is None or item.disposition.value != wanted:
            if wanted == Disposition.SHARED.value:
                errors.append(
                    f"same-name candidate {catalogue_id} needs a shared-method comparison"
                )
            else:
                errors.append(f"{catalogue_id} should be {wanted}")
        elif wanted == Disposition.SHARED.value and not item.method_compared:
            errors.append(
                f"same-name candidate {catalogue_id} needs a shared-method comparison"
            )

    maximum = expected.get("max_recommendations")
    recommendations = sum(
        item.disposition is Disposition.WORTH_BORROWING for item in ledger.entries
    )
    if isinstance(maximum, int) and recommendations > maximum:
        errors.append(f"recommend at most {maximum} Dex additions")
    return tuple(errors)


def _report_errors(
    report_markdown: str,
    ledger: ComparisonLedger,
    expected: Mapping[str, object],
) -> tuple[str, ...]:
    errors = list(missing_report_requirements(report_markdown))
    lowered = report_markdown.lower()
    if expected.get("requires_strength") and "## what is working especially well" not in lowered:
        errors.append("the report must include one evidenced strength")
    if expected.get("requires_reciprocal_answer"):
        if "## what dex should learn from you" not in lowered or ledger.reciprocal_answer in {
            "Unknown",
            "",
        }:
            errors.append("the report must include a grounded reciprocal answer")
    forbidden = expected.get("forbidden_claims", ())
    if isinstance(forbidden, list):
        for claim in forbidden:
            if str(claim).lower() in lowered:
                errors.append(f"forbidden unsupported claim: {claim}")
    return tuple(errors)


def evaluate_diagnosis(
    *,
    fingerprint: EvidenceFingerprint,
    ledger: ComparisonLedger,
    report_markdown: str,
    expected: Mapping[str, object],
) -> EvaluationResult:
    """Evaluate each layer independently so failures name their true source."""
    return EvaluationResult(
        observation_errors=_observation_errors(fingerprint, expected),
        capability_errors=_capability_errors(ledger, expected),
        comparison_errors=_comparison_errors(ledger, expected),
        report_errors=_report_errors(report_markdown, ledger, expected),
    )
