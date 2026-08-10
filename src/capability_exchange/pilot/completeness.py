"""Fail-closed R7 handoff-pack manifest and completeness verifier."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.pilot._common import clean_text, content_hash, tuple_text
from capability_exchange.pilot.drills import REQUIRED_RUNBOOK_IDS, TabletopResult

__all__ = [
    "CompletenessReport",
    "R7Artifact",
    "R7Manifest",
    "R7Risk",
    "R7Signoff",
    "R7CompletenessVerifier",
    "R7ManifestVerifier",
    "R7EvidenceStatus",
    "verify_r7_manifest",
]


REQUIRED_ARTIFACT_IDS = (
    "data-flow-trust-boundary",
    "retention-deletion-requirements",
    "browser-security-requirements",
    "consent-schema",
    "evidence-schema",
    "card-schema",
    "lifecycle-schema",
    "adapter-conformance-suite",
    "hostile-fixtures",
    "fault-injection-results",
    "incident-runbook",
    "hard-stop-runbook",
    "withdrawal-runbook",
    "key-rotation-runbook",
    "support-runbook",
    "risk-register",
    "journey-boundaries",
    "domain-state-model",
    "adapter-contract",
    "testable-gates",
    "pilot-protocol",
    "measurement-evidence-templates",
    "observed-pilot-evidence",
    "assumptions-non-goals",
    "critique-responses",
)


class R7EvidenceStatus(StrEnum):
    ABSENT = "absent"
    SYNTHETIC = "synthetic"
    OBSERVED = "observed"


class R7Artifact(InventoriedModel):
    """One manifest entry; existence and hash are checked against disk."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    path: str | None = None
    content_hash: str | None = None
    present: bool = False
    parseable: bool = False
    synthetic_only: bool = False
    observed: bool = False

    @field_validator("artifact_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return clean_text(value, label="artifact_id", max_length=128)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, label="path", max_length=1024)

    @field_validator("content_hash")
    @classmethod
    def _hash(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, label="content_hash", max_length=128)


class R7Risk(InventoriedModel):
    """Residual risk; an owner is mandatory for a complete pack."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    risk_id: str
    description: str
    owner: str | None = None
    status: str = "open"

    @field_validator("risk_id", "description", "status")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=1024)

    @field_validator("owner")
    @classmethod
    def _owner(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, label="owner", max_length=256)


class R7Signoff(InventoriedModel):
    """Independent review sign-off bound to the manifest content hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewer: str
    role: str
    independent: bool
    manifest_hash: str
    signed_at: datetime

    @field_validator("reviewer", "role", "manifest_hash")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=512)

    @field_validator("signed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("signed_at must be timezone-aware")
        return value


class R7Manifest(InventoriedModel):
    """Manifest of every required R7 artifact and its review status."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    manifest_version: int = Field(ge=1)
    artifacts: tuple[R7Artifact, ...] = ()
    risks: tuple[R7Risk, ...] = ()
    observed_pilot_evidence: tuple[str, ...] = ()
    observed_evidence_status: R7EvidenceStatus = R7EvidenceStatus.ABSENT
    assumptions: tuple[str, ...] = ()
    non_goals: tuple[str, ...] = ()
    critique_responses: tuple[str, ...] = ()
    tabletop_results: tuple[TabletopResult, ...] = ()
    content_hash: str | None = None
    independent_signoff: R7Signoff | None = None

    @field_validator(
        "observed_pilot_evidence",
        "assumptions",
        "non_goals",
        "critique_responses",
    )
    @classmethod
    def _lists(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple_text(value, label=info.field_name, max_items=256)

    @field_validator("content_hash")
    @classmethod
    def _hash(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, label="content_hash", max_length=128)

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash", "independent_signoff"})

    def canonical_hash(self) -> str:
        return content_hash(self.canonical_payload())

    @property
    def hash(self) -> str | None:
        return self.content_hash


class CompletenessReport(InventoriedModel):
    """Verifier output; ``complete`` is false for every unproven condition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    complete: bool
    issues: tuple[str, ...] = ()
    verified_artifacts: tuple[str, ...] = ()
    manifest_hash: str | None = None
    observed_real_pilot_evidence: bool = False
    named_risk_owners: bool = False
    independent_signoff: bool = False

    @field_validator("issues", "verified_artifacts")
    @classmethod
    def _lists(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple_text(value, label=info.field_name, max_items=512)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(
    value: R7Manifest | str | Path,
    root: Path | None,
) -> tuple[R7Manifest, Path | None]:
    if isinstance(value, R7Manifest):
        return value, root
    path = Path(value)
    manifest_root = root or path.parent
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return R7Manifest.model_validate(data), manifest_root
    except Exception as exc:  # noqa: BLE001 - verifier must report, never crash
        raise ValueError(f"R7 manifest could not be parsed: {type(exc).__name__}") from exc


def verify_r7_manifest(
    manifest: R7Manifest | str | Path,
    *,
    root: Path | None = None,
) -> CompletenessReport:
    """Return exact missing/invalid conditions; never infer a complete pack."""

    try:
        value, base = _load_manifest(manifest, root)
    except ValueError as exc:
        return CompletenessReport(complete=False, issues=(str(exc),))
    issues: list[str] = []
    verified: list[str] = []
    by_id: dict[str, R7Artifact] = {}
    for artifact in value.artifacts:
        if artifact.artifact_id in by_id:
            issues.append(f"duplicate artifact id: {artifact.artifact_id}")
        by_id[artifact.artifact_id] = artifact
    for required in REQUIRED_ARTIFACT_IDS:
        artifact = by_id.get(required)
        if artifact is None:
            issues.append(f"missing required artifact: {required}")
            continue
        if not artifact.present or not artifact.parseable:
            issues.append(f"artifact is missing or unparseable: {required}")
            continue
        if base is not None and artifact.path:
            path = (base / artifact.path).resolve()
            try:
                path.relative_to(base.resolve())
            except ValueError:
                issues.append(f"artifact path escapes manifest root: {required}")
                continue
            if not path.is_file() or path.stat().st_size == 0:
                issues.append(f"artifact file is missing or empty: {required}")
                continue
            if artifact.content_hash is None or artifact.content_hash != _hash_file(path):
                issues.append(f"artifact content hash is missing or invalid: {required}")
                continue
        elif artifact.content_hash is None:
            issues.append(f"artifact content hash is missing: {required}")
            continue
        verified.append(required)

    for risk in value.risks:
        if not risk.owner:
            issues.append(f"risk has no named owner: {risk.risk_id}")
    named_risk_owners = bool(value.risks) and all(bool(risk.owner) for risk in value.risks)

    observed = value.observed_evidence_status is R7EvidenceStatus.OBSERVED and bool(
        value.observed_pilot_evidence
    )
    if not observed:
        issues.append("observed real-pilot evidence is absent (synthetic evidence is not enough)")
    if not value.assumptions or not value.non_goals:
        issues.append("assumptions and explicit non-goals are required")
    if not value.critique_responses:
        issues.append("Fable critique responses are missing")

    tabletop_by_id = {result.runbook_id: result for result in value.tabletop_results}
    for runbook_id in REQUIRED_RUNBOOK_IDS:
        result = tabletop_by_id.get(runbook_id)
        if result is None or not result.passed or not result.exit_criteria_met:
            issues.append(f"runbook tabletop is missing or failed: {runbook_id}")

    expected_manifest_hash = value.canonical_hash()
    if value.content_hash is None:
        issues.append("manifest content hash is missing")
    elif value.content_hash != expected_manifest_hash:
        issues.append("manifest content hash does not match canonical content")

    signoff_ok = bool(
        value.independent_signoff
        and value.independent_signoff.independent
        and value.content_hash
        and value.independent_signoff.manifest_hash == value.content_hash
    )
    if not signoff_ok:
        issues.append("independent signoff is missing or is not bound to manifest hash")

    return CompletenessReport(
        complete=not issues,
        issues=tuple(issues),
        verified_artifacts=tuple(verified),
        manifest_hash=value.content_hash,
        observed_real_pilot_evidence=observed,
        named_risk_owners=named_risk_owners,
        independent_signoff=signoff_ok,
    )


# Common spelling used by release scripts.
verify_manifest = verify_r7_manifest


class R7CompletenessVerifier:
    """Small object wrapper for callers that prefer an explicit verifier."""

    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root

    def verify(self, manifest: R7Manifest | str | Path) -> CompletenessReport:
        return verify_r7_manifest(manifest, root=self.root)


R7ManifestVerifier = R7CompletenessVerifier
