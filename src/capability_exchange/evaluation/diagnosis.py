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
    observation_id_for,
)
from capability_exchange.diagnosis.report import (
    ledger_appendix_errors,
    ledger_derived_fact_errors,
)
from capability_exchange.diagnosis.significant_families import FamilyAssessmentDisposition
from capability_exchange.reports.store import missing_report_requirements

__all__ = [
    "EvaluationResult",
    "SignificantCoverageGrade",
    "evaluate_diagnosis",
    "grade_significant_coverage",
]


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


@dataclass(frozen=True)
class SignificantCoverageGrade:
    """Transparent 100-point grade with a non-negotiable critical-family gate."""

    family_completeness: int
    critical_family_recall: int
    axis_state_honesty: int
    reciprocal_strengths: int
    recommendation_usefulness: int
    privacy_read_only_completion: int
    critical_omissions: tuple[str, ...]

    def __post_init__(self) -> None:
        maxima = (30, 20, 15, 15, 10, 10)
        values = (
            self.family_completeness,
            self.critical_family_recall,
            self.axis_state_honesty,
            self.reciprocal_strengths,
            self.recommendation_usefulness,
            self.privacy_read_only_completion,
        )
        if any(
            value < 0 or value > maximum
            for value, maximum in zip(values, maxima, strict=True)
        ):
            raise ValueError("significant-coverage sub-score is outside its fixed maximum")
        if len(self.critical_omissions) != len(set(self.critical_omissions)):
            raise ValueError("critical omissions must be unique")

    @property
    def total(self) -> int:
        return (
            self.family_completeness
            + self.critical_family_recall
            + self.axis_state_honesty
            + self.reciprocal_strengths
            + self.recommendation_usefulness
            + self.privacy_read_only_completion
        )

    @property
    def passed(self) -> bool:
        return self.total >= 90 and not self.critical_omissions


def _proportional_score(*, observed: int, expected: int, maximum: int) -> int:
    if expected == 0:
        return maximum
    return maximum * min(observed, expected) // expected


def grade_significant_coverage(
    *,
    fingerprint: EvidenceFingerprint,
    ledger: ComparisonLedger,
    report_markdown: str,
    expected_family_ids: tuple[str, ...],
    expected_critical_family_ids: tuple[str, ...],
    unavailable_catalogue_ids: tuple[str, ...] = (),
    read_only_proven: bool = False,
    run_completed: bool = False,
) -> SignificantCoverageGrade:
    """Grade a completed run without embedding any private-vault expectations."""

    expected_families = set(expected_family_ids)
    family_by_id = {item.family_id: item for item in ledger.family_entries}
    expected_local_axes = {
        observation_id_for(item): (
            item.kind,
            item.identity,
            item.configuration_state,
            item.runtime_state,
            item.health_state,
        )
        for item in fingerprint.observations
    }
    actual_local_axes = {
        item.observation_id: (
            item.kind,
            item.identity,
            item.configuration_state,
            item.runtime_state,
            item.health_state,
        )
        for item in ledger.local_entries
    }
    exact_family_count = len(expected_families & set(family_by_id))
    family_score = _proportional_score(
        observed=exact_family_count,
        expected=len(expected_families),
        maximum=30,
    )
    if set(family_by_id) - expected_families:
        family_score = max(0, family_score - 5)

    critical_expected = set(expected_critical_family_ids)
    critical_recalled = {
        family_id
        for family_id in critical_expected
        if family_id in family_by_id
        and family_by_id[family_id].matched_components
        and set(family_by_id[family_id].matched_observation_ids).issubset(
            expected_local_axes
        )
        and family_by_id[family_id].disposition
        is not FamilyAssessmentDisposition.NOT_ASSESSED
    }
    critical_omissions = tuple(sorted(critical_expected - critical_recalled))
    critical_score = _proportional_score(
        observed=len(critical_recalled),
        expected=len(critical_expected),
        maximum=20,
    )

    axis_score = 5 if actual_local_axes == expected_local_axes else 0
    conservative_sentence = (
        "does not establish method equivalence, runtime quality, or outcomes"
    )
    if (
        all(
            not component.method_equivalent
            for family in ledger.family_entries
            for component in family.matched_components
        )
        and conservative_sentence in report_markdown
    ):
        axis_score += 5
    unresolved_visible = all(
        family.family_id in report_markdown
        and (
            not family.unresolved_components
            or (
                f"{len(family.unresolved_components)} "
                f"{'component' if len(family.unresolved_components) == 1 else 'components'} "
                f"{'remains' if len(family.unresolved_components) == 1 else 'remain'} Unknown"
            )
            in report_markdown
        )
        for family in ledger.family_entries
    )
    if unresolved_visible:
        axis_score += 5

    reciprocal_score = 0
    if "## What is working especially well" in report_markdown:
        reciprocal_score += 5
    if (
        "## What Dex should learn from you" in report_markdown
        and ledger.reciprocal_answer in report_markdown
    ):
        reciprocal_score += 5
    matched_observations = {
        observation_id
        for family in ledger.family_entries
        for observation_id in family.matched_observation_ids
    }
    matched_components = sum(len(family.matched_components) for family in ledger.family_entries)
    count_claims_are_exact = (
        f"{len(matched_observations)} evidence-bound "
        f"{'building block' if len(matched_observations) == 1 else 'building blocks'}"
        in report_markdown
        and f"{matched_components} exact signed " in report_markdown
    )
    if count_claims_are_exact and conservative_sentence in report_markdown:
        reciprocal_score += 5

    recommendations = {
        item.catalogue_id
        for item in ledger.entries
        if item.disposition is Disposition.WORTH_BORROWING
    }
    recommendation_score = 5 if len(recommendations) <= 3 else 0
    if not recommendations & set(unavailable_catalogue_ids):
        recommendation_score += 5

    privacy_score = 4 if read_only_proven else 0
    if run_completed:
        privacy_score += 4
    if not ledger_appendix_errors(report_markdown, ledger):
        privacy_score += 2

    return SignificantCoverageGrade(
        family_completeness=family_score,
        critical_family_recall=critical_score,
        axis_state_honesty=axis_score,
        reciprocal_strengths=reciprocal_score,
        recommendation_usefulness=recommendation_score,
        privacy_read_only_completion=privacy_score,
        critical_omissions=critical_omissions,
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
    errors.extend(ledger_derived_fact_errors(report_markdown, ledger))
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
