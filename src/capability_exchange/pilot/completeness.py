"""Fail-closed R7 handoff-pack manifest and completeness verifier."""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.pilot._common import clean_text, content_hash, tuple_text
from capability_exchange.pilot.drills import (
    REQUIRED_RUNBOOK_IDS,
    TABLETOP_SCENARIOS,
    TabletopResult,
    required_runbooks,
    validate_recovery_failure_evidence,
)
from capability_exchange.pilot.protocol import PilotProtocol

__all__ = [
    "CompletenessReport",
    "R7Artifact",
    "R7Manifest",
    "R7Risk",
    "R7Signoff",
    "ObservedEnrollmentEvidence",
    "ObservedPilotEvidence",
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
    "incident-tabletop-evidence",
    "hard-stop-tabletop-evidence",
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


_SHA256 = __import__("re").compile(r"^[0-9a-f]{64}$")


class ObservedEnrollmentEvidence(InventoriedModel):
    """One enrolled participant identity bound to protocol consent evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    participant_id: str
    stratum_id: str
    protocol_hash: str
    consent_record_hash: str

    @field_validator("participant_id", "stratum_id")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("protocol_hash", "consent_record_hash")
    @classmethod
    def _hash(cls, value: str, info: Any) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256")
        return value


class ObservedPilotEvidence(InventoriedModel):
    """Concrete R7 evidence schema bound to protocol, plans, cohort, and artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    protocol_hash: str
    locked_plan_hashes: tuple[str, ...] = Field(min_length=1)
    enrollments: tuple[ObservedEnrollmentEvidence, ...] = Field(min_length=6, max_length=8)
    artifact_hashes: tuple[str, ...] = Field(min_length=1)
    observed_at: datetime
    assumptions: tuple[str, ...] = Field(min_length=1)
    non_goals: tuple[str, ...] = Field(min_length=1)

    @field_validator("protocol_hash")
    @classmethod
    def _protocol_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("protocol_hash must be a lowercase SHA-256")
        return value

    @field_validator("locked_plan_hashes", "artifact_hashes")
    @classmethod
    def _hashes(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(not _SHA256.fullmatch(item) for item in value):
            raise ValueError(f"{info.field_name} must contain unique lowercase SHA-256 hashes")
        return value

    @field_validator("assumptions", "non_goals")
    @classmethod
    def _lists(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple_text(value, label=info.field_name, max_items=256)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("observed_at must be timezone-aware")
        return value

    def validate_bindings(self, *, verified_hashes: frozenset[str]) -> None:
        if len({item.participant_id for item in self.enrollments}) != len(self.enrollments):
            raise ValueError("observed evidence participant ids must be unique")
        if any(item.protocol_hash != self.protocol_hash for item in self.enrollments):
            raise ValueError("observed enrollment is not bound to the evidence protocol")
        strata = {"non-dex": 0, "dex-customized": 0}
        for item in self.enrollments:
            if item.stratum_id not in strata:
                raise ValueError("observed enrollment uses an undeclared pilot stratum")
            strata[item.stratum_id] += 1
        if not (4 <= strata["non-dex"] <= 5 and 2 <= strata["dex-customized"] <= 3):
            raise ValueError("observed evidence cohort does not meet locked stratum quotas")
        if not set(self.locked_plan_hashes) <= set(self.artifact_hashes):
            raise ValueError("locked measurement plans are not bound into artifact hashes")
        if not set(self.artifact_hashes) <= set(verified_hashes):
            raise ValueError("observed evidence references an unverified artifact hash")


class SignoffSignatureVerifier(Protocol):
    def verify(self, payload: bytes, signature: str, key_id: str) -> bool: ...


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
    reviewer_id: str
    role: str
    independent: bool
    manifest_hash: str
    evidence_hash: str
    verifier_key_id: str
    signature: str
    signed_at: datetime

    @field_validator(
        "reviewer",
        "reviewer_id",
        "role",
        "manifest_hash",
        "evidence_hash",
        "verifier_key_id",
        "signature",
    )
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=512)

    @field_validator("signed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("signed_at must be timezone-aware")
        return value

    @property
    def signed_payload(self) -> bytes:
        return json.dumps(
            {
                "evidence_hash": self.evidence_hash,
                "manifest_hash": self.manifest_hash,
                "reviewer_id": self.reviewer_id,
                "role": self.role,
                "signed_at": self.signed_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


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


def _artifact_is_parseable(path: Path) -> bool:
    """Parse the actual artifact bytes; never trust a manifest checkbox."""

    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return False
        if path.suffix == ".json":
            json.loads(text)
        elif path.suffix == ".py":
            ast.parse(text, filename=str(path))
    except (OSError, UnicodeDecodeError, ValueError, SyntaxError, json.JSONDecodeError):
        return False
    return True


def _load_manifest(
    value: R7Manifest | str | Path,
    root: Path | None,
    evidence_verifier: SignoffSignatureVerifier | None,
    trusted_evidence_key_ids: frozenset[str],
) -> tuple[R7Manifest, Path | None]:
    context = {
        "evidence_root": root,
        "evidence_verifier": evidence_verifier,
        "trusted_evidence_key_ids": trusted_evidence_key_ids,
    }
    if isinstance(value, R7Manifest):
        return (
            R7Manifest.model_validate(
                value.model_dump(mode="python"), context=context
            ),
            root,
        )
    path = Path(value)
    manifest_root = root or path.parent
    context["evidence_root"] = manifest_root
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            R7Manifest.model_validate(
                data, context=context
            ),
            manifest_root,
        )
    except Exception as exc:  # noqa: BLE001 - verifier must report, never crash
        raise ValueError(f"R7 manifest could not be parsed: {type(exc).__name__}") from exc


def verify_r7_manifest(
    manifest: R7Manifest | str | Path,
    *,
    root: Path | None = None,
    signoff_verifier: SignoffSignatureVerifier | None = None,
    trusted_reviewer_ids: frozenset[str] = frozenset(),
    trusted_verifier_key_ids: frozenset[str] = frozenset(),
) -> CompletenessReport:
    """Return exact missing/invalid conditions; never infer a complete pack."""

    try:
        value, base = _load_manifest(
            manifest, root, signoff_verifier, trusted_verifier_key_ids
        )
    except ValueError as exc:
        detail = " ".join(str(exc).split())[:440]
        return CompletenessReport(
            complete=False,
            issues=(f"R7 manifest failed schema revalidation: {detail}",),
        )
    issues: list[str] = []
    verified: list[str] = []
    if base is None:
        issues.append("a filesystem root is required; in-memory flags are not evidence")
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
        if artifact.path is None:
            issues.append(f"artifact path is missing: {required}")
            continue
        if base is not None:
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
            if not _artifact_is_parseable(path):
                issues.append(f"artifact is not actually parseable: {required}")
                continue
        else:
            continue
        verified.append(required)

    for risk in value.risks:
        if not risk.owner:
            issues.append(f"risk has no named owner: {risk.risk_id}")
    named_risk_owners = bool(value.risks) and all(bool(risk.owner) for risk in value.risks)

    observed_artifact = by_id.get("observed-pilot-evidence")
    observed_marker = bool(
        value.observed_evidence_status is R7EvidenceStatus.OBSERVED
        and observed_artifact is not None
        and observed_artifact.artifact_id in verified
        and observed_artifact.observed
        and not observed_artifact.synthetic_only
        and observed_artifact.content_hash
        and observed_artifact.content_hash in value.observed_pilot_evidence
    )
    observed_schema: ObservedPilotEvidence | None = None
    if observed_marker and base is not None and observed_artifact and observed_artifact.path:
        try:
            observed_payload = json.loads(
                (base / observed_artifact.path).read_text(encoding="utf-8")
            )
            observed_schema = ObservedPilotEvidence.model_validate(observed_payload)
            observed_schema.validate_bindings(
                verified_hashes=frozenset(
                    item.content_hash or ""
                    for item in by_id.values()
                    if item.artifact_id in verified
                )
            )
            protocol_artifact = by_id.get("pilot-protocol")
            if protocol_artifact is None or not protocol_artifact.path:
                raise ValueError("observed evidence has no verified protocol artifact")
            protocol_payload = json.loads(
                (base / protocol_artifact.path).read_text(encoding="utf-8")
            )
            protocol = PilotProtocol.model_validate(protocol_payload)
            protocol.assert_red_team_ready()
            if protocol.protocol_hash != observed_schema.protocol_hash:
                raise ValueError("observed evidence does not match the protocol artifact")
        except Exception as exc:  # noqa: BLE001 - observed evidence fails closed
            issues.append(
                "observed pilot evidence schema or binding is invalid: "
                f"{type(exc).__name__}"
            )
    observed = observed_marker and observed_schema is not None
    if not observed:
        issues.append("observed real-pilot evidence is absent (synthetic evidence is not enough)")
    if not value.assumptions or not value.non_goals:
        issues.append("assumptions and explicit non-goals are required")
    if not value.critique_responses:
        issues.append("Fable critique responses are missing")

    tabletop_by_id = {result.runbook_id: result for result in value.tabletop_results}
    if len(tabletop_by_id) != len(value.tabletop_results):
        issues.append("duplicate runbook tabletop identity")
    unknown_tabletops = set(tabletop_by_id) - set(REQUIRED_RUNBOOK_IDS)
    if unknown_tabletops:
        issues.append("unknown runbook tabletop identity")
    runbooks_by_id = {runbook.runbook_id: runbook for runbook in required_runbooks()}
    for runbook_id in REQUIRED_RUNBOOK_IDS:
        result = tabletop_by_id.get(runbook_id)
        expected_scenario, expected_trigger = TABLETOP_SCENARIOS[runbook_id]
        artifact = by_id.get(f"{runbook_id}-runbook")
        recovery_evidence_ok = False
        tabletop_artifact = by_id.get(f"{runbook_id}-tabletop-evidence")
        if (
            runbook_id in {"incident", "hard-stop"}
            and result is not None
            and base is not None
            and result.execution_artifact_path
            and result.execution_artifact_hash
            and tabletop_artifact is not None
            and tabletop_artifact.artifact_id in verified
            and tabletop_artifact.path == result.execution_artifact_path
            and tabletop_artifact.content_hash == result.execution_artifact_hash
        ):
            try:
                evidence_path = (base / result.execution_artifact_path).resolve()
                evidence_path.relative_to(base.resolve())
                evidence = validate_recovery_failure_evidence(
                    evidence_path,
                    result.execution_artifact_hash,
                    verifier=signoff_verifier,
                    trusted_key_ids=trusted_verifier_key_ids,
                )
                recovery_evidence_ok = (
                    evidence.runbook_id == runbook_id
                    and evidence.scenario_id == expected_scenario
                    and evidence.transaction_journal.transaction_id
                    == result.transaction_id
                )
            except Exception:  # noqa: BLE001 - malformed evidence is incomplete
                recovery_evidence_ok = False
        if (
            result is None
            or not result.trigger_observed
            or not result.exit_criteria_met
            or result.scenario_id != expected_scenario
            or result.trigger_id != expected_trigger
            or result.actions_evidenced != runbooks_by_id[runbook_id].actions
            or artifact is None
            or result.runbook_artifact_hash != artifact.content_hash
            or (
                runbook_id in {"incident", "hard-stop"}
                and not recovery_evidence_ok
            )
            or (
                runbook_id not in {"incident", "hard-stop"}
                and not (
                    result.passed and result.trigger_observed and result.exit_criteria_met
                )
            )
            or (runbook_id == "withdrawal" and not result.deletion_verified)
        ):
            issues.append(f"runbook tabletop is missing or failed: {runbook_id}")

    expected_manifest_hash = value.canonical_hash()
    if value.content_hash is None:
        issues.append("manifest content hash is missing")
    elif value.content_hash != expected_manifest_hash:
        issues.append("manifest content hash does not match canonical content")

    signature_ok = False
    if value.independent_signoff and signoff_verifier is not None:
        try:
            signature_ok = bool(
                signoff_verifier.verify(
                    value.independent_signoff.signed_payload,
                    value.independent_signoff.signature,
                    value.independent_signoff.verifier_key_id,
                )
            )
        except Exception:  # noqa: BLE001 - trust verification fails closed
            signature_ok = False
    signoff_ok = bool(
        value.independent_signoff
        and value.independent_signoff.independent
        and value.independent_signoff.reviewer_id in trusted_reviewer_ids
        and value.independent_signoff.verifier_key_id in trusted_verifier_key_ids
        and value.content_hash
        and value.independent_signoff.manifest_hash == value.content_hash
        and observed_artifact is not None
        and value.independent_signoff.evidence_hash == observed_artifact.content_hash
        and signature_ok
    )
    if not signoff_ok:
        issues.append(
            "independent signoff is missing or lacks a trusted reviewer/verifier binding"
        )

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

    def __init__(
        self,
        *,
        root: Path | None = None,
        signoff_verifier: SignoffSignatureVerifier | None = None,
        trusted_reviewer_ids: frozenset[str] = frozenset(),
        trusted_verifier_key_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.root = root
        self.signoff_verifier = signoff_verifier
        self.trusted_reviewer_ids = trusted_reviewer_ids
        self.trusted_verifier_key_ids = trusted_verifier_key_ids

    def verify(self, manifest: R7Manifest | str | Path) -> CompletenessReport:
        return verify_r7_manifest(
            manifest,
            root=self.root,
            signoff_verifier=self.signoff_verifier,
            trusted_reviewer_ids=self.trusted_reviewer_ids,
            trusted_verifier_key_ids=self.trusted_verifier_key_ids,
        )


R7ManifestVerifier = R7CompletenessVerifier
