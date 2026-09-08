"""Deep deterministic diagnosis engine. CLI and MCP are thin adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol, get_args

from pydantic import BaseModel, Field, ValidationError

from capability_exchange.concierge.consent import (
    LocalScopeConsentAuthority,
    opaque_candidate_locator,
)
from capability_exchange.diagnosis.comparison import ComparisonLedger, Disposition
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    ObservationOrigin,
    derive_observation_origin,
    observation_key_for,
    upgrade_stored_fingerprint_payload,
)
from capability_exchange.diagnosis.payload_guard import (
    HostilePayloadError,
    refuse_hostile_payload,
)
from capability_exchange.diagnosis.provenance import SourceClass
from capability_exchange.diagnosis.ranking import RecommendationFactors
from capability_exchange.diagnosis.report import (
    ReportModel,
    canonical_fact_block,
    canonical_ledger_appendix,
    canonical_ledger_digest,
    canonical_ledger_payload,
    ledger_appendix_errors,
)
from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    INPUT_SCHEMA_VERSION,
    INTAKE_NOT_SURE,
    INTAKE_PROJECT_LINK,
    INTAKE_QUESTION_OPTIONS,
    NEXT_ACTION,
    NEXT_STAGE,
    ApprovedScopeReceipt,
    DiagnosisCheckpoint,
    DiagnosisInput,
    DiagnosisRunView,
    DiagnosisStage,
    DiagnosisStateError,
    FamilyDiveProgress,
    FamilyDiveState,
    FamilyMap,
    FocusReceipt,
    IntakeAnswer,
    IntakeReceipt,
    RequiredStep,
    RunIdentity,
    WorkProgress,
    _ValidatedInventoried,
    advance_inventory_to_compare,
    advance_to,
    canonical_json_digest,
    intake_answer_fault,
    intake_required_question_ids,
    progress_headline,
    required_step_for_stage,
)
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.significant_families import is_non_lineage
from capability_exchange.diagnosis.specialists import (
    JOB_DISAGREEMENT_REASON,
    MAX_EVIDENCE_IDS,
    MAX_RECOMMENDATIONS,
    CandidateBaseline,
    ProposalContext,
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    ValidatedProposal,
    disagreement_reason,
    mint_evidence_token,
    reconcile_proposals,
    validate_proposal,
)
from capability_exchange.diagnosis.work import (
    MAX_PROPOSALS_PER_PACKET,
    AnalysisMode,
    WorkAudit,
    WorkPacket,
    WorkQueue,
    WorkQueueError,
    WorkReceipt,
    WorkStatus,
    build_work_queue,
    focus_job_primary_role,
    focus_primary_role,
)
from capability_exchange.reports.store import LensReportStore

__all__ = [
    "ADAPTER_VERSION",
    "ComparisonBuilder",
    "DeterministicDiagnosisEngine",
    "DiagnosisResult",
    "EvidenceLegendRow",
    "FingerprintCollector",
    "MAX_FACTOR_TUPLES_PER_CANDIDATE",
    "PrepareDiagnosisRequest",
    "VerifiedCatalogueLoader",
    "VerifiedCatalogueSlice",
    "fingerprint_digest_for",
]

ADAPTER_VERSION = "injected-collector"

# A disputed recommendation baseline carries at most one distinct complete
# factor tuple per closed specialist role
# (``CandidateBaseline.disputed_recommendation_factors`` is capped at
# ``len(SpecialistRole)``).  Enforcing the same numeric cap at submission —
# before any normal response becomes a final receipt — keeps that baseline
# constructible for the sceptical packet, so a valid-input run can never wedge
# there with no exit.
MAX_FACTOR_TUPLES_PER_CANDIDATE = len(SpecialistRole)

# Stages at which the deterministic family map cannot exist yet: the map is
# derived from the captured fingerprint and the verified catalogue, so it
# becomes readable only once the run reaches (or, for runs saved before the
# stage existed, has passed) FAMILY_MAPPED.
_PRE_FAMILY_MAP_STAGES = frozenset(
    {
        DiagnosisStage.CREATED,
        DiagnosisStage.SCOPE_APPROVED,
        DiagnosisStage.CAPTURED,
        DiagnosisStage.CATALOGUE_VERIFIED,
    }
)


def _collect_declared_models(
    annotation: object, into: dict[str, frozenset[str]]
) -> None:
    """Register every engine model reachable from one annotation, by name."""

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation.__name__ in into:
            return
        into[annotation.__name__] = frozenset(annotation.model_fields)
        for field in annotation.model_fields.values():
            _collect_declared_models(field.annotation, into)
        return
    for argument in get_args(annotation):
        _collect_declared_models(argument, into)


@lru_cache(maxsize=1)
def _declared_fields_by_model() -> dict[str, frozenset[str]]:
    """Field-name allowlists for every model a typed refusal may describe.

    The closure is engine-owned: the ledger and run-identity roots plus every
    model reachable through their declared field annotations.  It mirrors the
    ``payload_guard`` boundary — a refusal may echo only names declared on
    these models, never a key taken from a submitted or stored payload.
    """

    declared: dict[str, frozenset[str]] = {}
    for root in (ComparisonLedger, RunIdentity):
        _collect_declared_models(root, declared)
    return declared


def _typed_model_refusal(action: str, exc: ValidationError) -> DiagnosisStateError:
    """Translate a typed-model failure into a named, value-free refusal.

    Pydantic's own messages repeat the offending input, which on this path can
    be specialist or vault text; they are deliberately not consulted.  The
    location of an ``extra_forbidden`` error is the SUBMITTED dictionary key —
    attacker-controlled text on a tampered artifact — so locations are not
    trusted either: only names present in the failing engine model's own
    declared field set are quoted, in fixed wording, and every other location
    collapses to a count.  A compare failure therefore tells the operator what
    broke without leaking what it broke on.
    """

    declared = _declared_fields_by_model().get(exc.title, frozenset())
    named: set[str] = set()
    unknown = 0
    for error in exc.errors(include_url=False, include_input=False):
        location = error.get("loc") or ()
        if not location:
            continue
        head = location[0]
        if isinstance(head, str) and head in declared:
            named.add(head)
        else:
            unknown += 1
    parts: list[str] = []
    if named:
        parts.append(f"failing fields: {', '.join(sorted(named))}")
    if unknown:
        parts.append("an unknown field" if unknown == 1 else f"{unknown} unknown fields")
    detail = (
        f" ({'; '.join(parts)})"
        if parts
        else " (a model-level consistency rule failed)"
    )
    return DiagnosisStateError(
        f"{action} an invalid {exc.title} value{detail}; no conclusion was recorded"
    )


def payload_digest(payload: object) -> str:
    """Return 64 hex characters over sorted compact JSON."""

    return canonical_json_digest(payload).removeprefix("sha256:")


def fingerprint_digest_for(fingerprint: EvidenceFingerprint) -> str:
    """Stable sha256: digest of one fingerprint payload."""

    return "sha256:" + payload_digest(fingerprint.model_dump(mode="json"))


@dataclass(frozen=True)
class _CandidateDispute:
    """The facts of one specialist dispute, kept for the sceptical baseline.

    Internal reconciliation state, never persisted: the sorted set of
    dispositions the normal packets proposed for one candidate, and — for a
    disputed recommendation — the complete factor tuples they proposed.
    """

    dispositions: tuple[Disposition, ...]
    recommendation_factor_tuples: tuple[RecommendationFactors, ...]


@dataclass(frozen=True)
class PrepareDiagnosisRequest:
    """Candidate folders recorded without reading them."""

    roots: tuple[Path, ...]
    analysis_mode: AnalysisMode = AnalysisMode.GUIDED

    @classmethod
    def from_roots(cls, roots: Sequence[Path | str]) -> PrepareDiagnosisRequest:
        if not roots:
            raise DiagnosisStateError("diagnosis prepare requires at least one candidate root")
        return cls(roots=tuple(Path(root) for root in roots))


class EvidenceLegendRow(_ValidatedInventoried):
    """One local legend row binding an engine-minted token to its observation.

    Everything here is drawn from the already privacy-screened fingerprint:
    labels and relative references are local-only and stay in the same trust
    domain as the fingerprint artifact on disk.  The legend rides alongside
    the work packet — it never joins the packet's digest-bound identity.
    """

    evidence_id: str = Field(pattern=r"^evidence:sha256:[0-9a-f]{64}$")
    observation_id: str = Field(pattern=r"^observation:sha256:[0-9a-f]{64}$")
    kind: ObservationKind
    identity: str
    label: str = Field(min_length=1, max_length=160)
    relative_reference: str = Field(min_length=1, max_length=240)
    source_class: SourceClass

    @classmethod
    def for_observation(
        cls,
        observation: Observation,
        *,
        run_id: str,
        fingerprint_digest: str,
    ) -> EvidenceLegendRow:
        """Build the row for one observation with its engine-minted token."""

        return cls(
            evidence_id=mint_evidence_token(
                run_id=run_id,
                fingerprint_digest=fingerprint_digest,
                observation_key=observation_key_for(observation),
            ),
            observation_id=observation.observation_id,
            kind=observation.kind,
            identity=observation.identity,
            label=observation.label,
            relative_reference=observation.provenance.relative_reference,
            source_class=observation.provenance.source_class,
        )


@dataclass(frozen=True)
class VerifiedCatalogueSlice:
    """Lawful catalogue facts the engine may consume. Not a second catalogue."""

    version: int
    sha256: str
    catalogue_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    unavailable_ids: tuple[str, ...] = ()
    family_contract_present: bool = False
    core_release: str | None = None
    #: Kind-qualified identities the signed catalogue names, derived by the
    #: loader from the signature-verified envelope on every load.  The engine
    #: keys each observation's authorship origin on this set; it is never
    #: written to or read back from the stored catalogue artifact, so a stored
    #: copy can never launder a different identity set into the derivation.
    signed_identity_keys: tuple[str, ...] = ()
    #: (family_id, member capability ids) pairs from the signed family
    #: contract, loader-derived from the signature-verified envelope on every
    #: load and never read back from a stored artifact.  Focused runs derive
    #: every packet's catalogue/capability identity slice from exactly this
    #: set, so nothing host-supplied can enter a slice.
    signed_family_members: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: Signed jobs-taxonomy identities, loader-derived from the
    #: signature-verified envelope on every load.  On a non-lineage run these
    #: are the only identities a job-coverage proposal may name.
    signed_job_ids: tuple[str, ...] = ()
    #: (job_id, capability ids serving that job) pairs, loader-derived from
    #: the signature-verified envelope on every load.  Focused non-lineage
    #: runs derive every packet's identity slice from exactly this set —
    #: job-keyed slices, never host-supplied.
    signed_job_members: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class DiagnosisResult:
    """Closed typed result. Markdown is rendered from the bound report and ledger."""

    report: ReportModel
    ledger: ComparisonLedger

    def dump_for_storage(self) -> dict[str, object]:
        return {
            "ledger": canonical_ledger_payload(self.ledger),
            "ledger_appendix": canonical_ledger_appendix(self.ledger),
            "ledger_sha256": self.report.ledger_sha256,
            "report": self.report.model_dump(mode="json"),
            "run_id": self.report.run_identity.run_id,
            "stage": DiagnosisStage.CLOSED.value,
        }

    def render_markdown(self) -> str:
        return self.report.render_markdown(self.ledger)

    def ledger_json(self) -> str:
        return json.dumps(
            canonical_ledger_payload(self.ledger),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def with_report_location(self, path: Path) -> DiagnosisResult:
        """Bind the exact app-storage destination before canonical rendering."""

        return DiagnosisResult(
            report=self.report.with_report_location(path),
            ledger=self.ledger,
        )


class FingerprintCollector(Protocol):
    """Constructor-injected wrap over existing collection. Not a second stack."""

    def collect(self, receipt: ApprovedScopeReceipt) -> EvidenceFingerprint: ...


class VerifiedCatalogueLoader(Protocol):
    """Constructor-injected wrap over VerifiedCatalogueStore."""

    def load(self, *, run_id: str, fingerprint_digest: str) -> VerifiedCatalogueSlice: ...


class ComparisonBuilder(Protocol):
    """Constructor-injected wrap over ComparisonLedger construction.

    ``focus`` (the validated :class:`FocusReceipt`) is passed by keyword only
    on focused runs, so comparers written before the mode existed keep their
    exact signature.
    """

    def compare(
        self,
        *,
        fingerprint: EvidenceFingerprint,
        catalogue: VerifiedCatalogueSlice,
        jobs: tuple[object, ...],
        proposals: tuple[ValidatedProposal, ...],
        work_audit: WorkAudit | None = None,
    ) -> ComparisonLedger: ...



def _intake_answer_set_fault(answers: Mapping[str, str]) -> str | None:
    """Why a submitted answer set is not acceptable, in plain words.

    Deterministic order: unknown questions first (sorted), then a bad answer
    (branch order), then the first missing question (branch order), then the
    first question that does not belong to this branch (sorted).
    """

    known = set(INTAKE_QUESTION_OPTIONS) | {INTAKE_PROJECT_LINK}
    unknown = sorted(set(answers) - known)
    if unknown:
        return f"'{unknown[0]}' is not an intake question"
    for question_id in sorted(answers):
        fault = intake_answer_fault(question_id, answers[question_id])
        if fault is not None:
            return fault
    required = intake_required_question_ids(answers)
    for question_id in required:
        if question_id not in answers:
            return (
                f"'{question_id}' is unanswered; every question takes "
                f"'{INTAKE_NOT_SURE}' if you do not know"
            )
    extra = sorted(set(answers) - set(required))
    if extra:
        return f"'{extra[0]}' is not one of this run's intake questions"
    return None


class DeterministicDiagnosisEngine:
    """Owns lawful diagnosis transitions. Dependencies are injected."""

    def __init__(
        self,
        *,
        run_store: DiagnosisRunStore,
        consent_authority: LocalScopeConsentAuthority,
        collector: FingerprintCollector,
        catalogue_loader: VerifiedCatalogueLoader,
        comparer: ComparisonBuilder,
        report_store: LensReportStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._runs = run_store
        self._consent = consent_authority
        self._collector = collector
        self._catalogues = catalogue_loader
        self._compare = comparer
        self._reports = report_store
        self._clock = clock

    @property
    def consent_authority(self) -> LocalScopeConsentAuthority:
        """The only authority CLI/MCP may attach to the local /approve surface."""

        return self._consent

    @property
    def run_store(self) -> DiagnosisRunStore:
        """The durable checkpoint store later CLI commands resume from."""

        return self._runs

    def prepare(self, request: object) -> DiagnosisRunView:
        """Record candidate folders. Read nothing and do not collect."""

        roots = tuple(Path(root).expanduser().resolve() for root in request.roots)
        try:
            analysis_mode = AnalysisMode(
                # Requests from pre-guided adapters have no mode field.  Treat
                # that missing field as the explicit compatibility path; the
                # engine request model itself defaults new runs to guided.
                getattr(request, "analysis_mode", AnalysisMode.INVENTORY_ONLY)
            )
        except ValueError as exc:
            raise DiagnosisStateError("unsupported diagnosis analysis mode") from exc
        view = self._consent.prepare(candidate_roots=roots)
        self._runs.save_candidate_scope(
            view.run_id,
            candidate_roots=tuple(str(root) for root in roots),
            locators=tuple(opaque_candidate_locator(root) for root in roots),
            analysis_mode=analysis_mode,
        )
        now = self._clock()
        run_identity = RunIdentity(
            run_id=view.run_id,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            analysis_mode=analysis_mode.value,
            created_at=now,
        )
        identity = canonical_json_digest(
            {"engine_version": ENGINE_VERSION, "run_id": view.run_id}
        )
        artifact = self._put("run-identity", run_identity.dump_for_storage())
        self._runs.save(
            DiagnosisCheckpoint(
                run_id=view.run_id,
                stage=DiagnosisStage.CREATED,
                previous_digest=None,
                input_identity=identity,
                artifact_digests=(artifact,),
                next_action=NEXT_ACTION[DiagnosisStage.CREATED],
                engine_version=ENGINE_VERSION,
                created_at=now,
            )
        )
        return view

    def status(self, run_id: str) -> DiagnosisRunView:
        checkpoint = self._load(run_id)
        view = self._view(checkpoint)
        if checkpoint.stage in _PRE_FAMILY_MAP_STAGES:
            return view
        try:
            family_map = self._derived_family_map(checkpoint)
        except DiagnosisStateError:
            # Status reports proved progress without advancing; a run whose
            # stored inputs cannot re-derive the map (for example a tampered
            # catalogue slice) still shows its stage, while every mutating or
            # map-specific surface keeps failing closed with the typed error.
            family_map = None
        try:
            intake = self._intake_receipt(checkpoint)
        except DiagnosisStateError:
            # Same discipline as the map: a tampered intake record never
            # reaches a reader through status, and every mutating surface
            # keeps failing closed with the typed error.
            intake = None
        try:
            focus = self._focus_receipt(checkpoint)
        except DiagnosisStateError:
            # Same discipline as the map: a tampered focus receipt never
            # reaches a reader through status, and every mutating or
            # focus-consuming surface keeps failing closed with the typed
            # error.
            focus = None
        progress: WorkProgress | None = None
        if checkpoint.stage is DiagnosisStage.ANALYSIS_PLANNED:
            try:
                progress = self._work_progress(checkpoint, family_map, focus)
            except DiagnosisStateError:
                # Same discipline again: status reports proved progress
                # without advancing, so a queue or record that cannot be
                # loaded leaves the progress block absent while every
                # mutating surface keeps failing closed with the typed error.
                progress = None
        update: dict[str, object] = {}
        if family_map is not None:
            update["family_map"] = family_map
        if focus is not None:
            update["focus"] = focus
        if intake is not None:
            update["intake"] = intake
        if progress is not None:
            update["progress"] = progress
        if not update:
            return view
        return view.model_copy(update=update)

    def family_map(self, run_id: str) -> FamilyMap:
        """Re-derive the deterministic family map for one run's read surfaces.

        Never loads the stored ``family-map`` artifact: the map is re-derived
        from the stored verified inputs on every read, so a tampered stored
        map cannot reach a reader (RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT).
        """

        checkpoint = self._load(run_id)
        if checkpoint.stage in _PRE_FAMILY_MAP_STAGES:
            raise DiagnosisStateError(
                "the family map is derived after catalogue verification",
                required_step=RequiredStep.MAP_FAMILIES,
            )
        family_map = self._derived_family_map(checkpoint)
        if family_map is None:
            raise DiagnosisStateError(
                "this engine's comparer cannot derive a family map"
            )
        return family_map

    def _derived_family_map(self, checkpoint: DiagnosisCheckpoint) -> FamilyMap | None:
        """Derive the map from stored verified inputs, or ``None`` for a
        comparer without the derivation (injected test doubles)."""

        derive = getattr(self._compare, "family_map", None)
        if not callable(derive):
            return None
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        return derive(fingerprint=fingerprint, catalogue=catalogue)

    def intake(self, run_id: str, answers: Mapping[str, str]) -> DiagnosisRunView:
        """Record the person's intake answers as an engine-minted receipt.

        Lawful exactly once, at scope approval, before anything beyond the
        approved folder listing is read. An identical replay is a no-op; a
        different answer set fails closed — the questions are asked once and
        answered once, and a change of mind means a new run.
        """

        with self._runs.exclusive(run_id):
            return self._intake_locked(run_id, dict(answers))

    def _intake_locked(
        self, run_id: str, answers: dict[str, str]
    ) -> DiagnosisRunView:
        checkpoint = self._load(run_id)
        if checkpoint.stage is DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis is closed; it exposes no mutation port")
        existing = self._intake_receipt(checkpoint)
        if existing is not None:
            recorded = {item.question_id: item.answer for item in existing.answers}
            if recorded == answers:
                # An exact replay of the recorded answers is idempotent.
                return self._view(checkpoint).model_copy(update={"intake": existing})
            raise DiagnosisStateError(
                "a different answer set is already recorded for this run; "
                "start a new run to answer differently"
            )
        if checkpoint.stage is DiagnosisStage.CREATED:
            raise DiagnosisStateError(
                "the intake questions follow the scope approval",
                required_step=RequiredStep.APPROVE_SCOPE,
            )
        if checkpoint.stage is not DiagnosisStage.SCOPE_APPROVED:
            raise DiagnosisStateError(
                "the intake window closed when this run moved on; answers "
                "shape a run from its start, so record them on a new run"
            )
        fault = _intake_answer_set_fault(answers)
        if fault is not None:
            raise DiagnosisStateError(fault, required_step=RequiredStep.RECORD_INTAKE)
        ordered = tuple(
            IntakeAnswer(question_id=question_id, answer=answers[question_id])
            for question_id in sorted(answers)
        )
        receipt = IntakeReceipt(
            run_id=checkpoint.run_id,
            answers=ordered,
            intake_digest=canonical_json_digest(
                {
                    "answers": [
                        {"answer": item.answer, "question_id": item.question_id}
                        for item in ordered
                    ],
                    "run_id": checkpoint.run_id,
                }
            ),
        )
        payload = receipt.dump_for_storage()
        try:
            refuse_hostile_payload(payload)
        except HostilePayloadError as exc:
            raise DiagnosisStateError(
                "intake answers carry content the engine refuses to retain"
            ) from exc
        artifact = self._put("intake-receipt", payload)
        identity = canonical_json_digest(
            {"engine_version": ENGINE_VERSION, "intake_digest": receipt.intake_digest}
        )
        updated = self._advance(
            checkpoint,
            DiagnosisStage.INTAKE_RECORDED,
            artifacts=(artifact,),
            input_identity=identity,
        )
        return self._view(updated).model_copy(update={"intake": receipt})

    def _intake_receipt(self, checkpoint: DiagnosisCheckpoint) -> IntakeReceipt | None:
        """Load and re-validate the stored intake receipt, or ``None``.

        The stored artifact is never trusted alone: the receipt recomputes its
        own digest from its recorded answers inside validation, so an edited
        answer no longer matches and the consuming surface fails closed.
        """

        payload = self._find_kind(checkpoint, "intake-receipt")
        if payload is None:
            return None
        try:
            receipt = IntakeReceipt.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored intake answers are unreadable") from exc
        if receipt.run_id != checkpoint.run_id:
            raise DiagnosisStateError(
                "stored intake answers do not belong to this run"
            )
        return receipt

    def _require_intake_answers(
        self, checkpoint: DiagnosisCheckpoint
    ) -> DiagnosisCheckpoint:
        """The advance handler for the intake stage: it can only refuse.

        The answers come from a person, so the engine can never take this
        step by itself — the refusal names the first unanswered question and
        the step that records them.
        """

        receipt = self._intake_receipt(checkpoint)
        if receipt is not None:  # pragma: no cover - advance() dispatch guard
            return checkpoint
        first = intake_required_question_ids({})[0]
        raise DiagnosisStateError(
            f"this run needs your answers first: '{first}' is unanswered. "
            "Record them with dex-lens diagnosis intake",
            required_step=RequiredStep.RECORD_INTAKE,
        )

    def focus(self, run_id: str, family_ids: Sequence[str]) -> DiagnosisRunView:
        """Record the person's family multi-select as an engine-minted receipt.

        Lawful only on a focused-analysis run in the window the family map
        opens (stage ``family-mapped``).  The receipt binds the exact selected
        family identities, the families explicitly not selected, and the
        digest of the re-derived family map the choice was made against.  An
        identical replay is a no-op; a different selection fails closed.
        """

        with self._runs.exclusive(run_id):
            return self._focus_locked(run_id, tuple(family_ids))

    def _focus_locked(self, run_id: str, family_ids: tuple[str, ...]) -> DiagnosisRunView:
        checkpoint = self._load(run_id)
        if checkpoint.stage is DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis is closed; it exposes no mutation port")
        if self._analysis_mode(checkpoint) is not AnalysisMode.FOCUSED:
            raise DiagnosisStateError(
                "a family focus selection is only valid on a focused-analysis run"
            )
        if checkpoint.stage in _PRE_FAMILY_MAP_STAGES:
            raise DiagnosisStateError(
                "the family selection follows the deterministic family map",
                required_step=RequiredStep.MAP_FAMILIES,
            )
        selection = tuple(sorted(set(family_ids)))
        if not selection:
            raise DiagnosisStateError(
                "a focus selection must name at least one family from the family map"
            )
        existing = self._focus_receipt(checkpoint)
        if existing is not None:
            if existing.selected_family_ids == selection:
                # An exact replay of the recorded selection is idempotent.
                return self._view(checkpoint).model_copy(update={"focus": existing})
            raise DiagnosisStateError(
                "a different focus selection is already recorded for this run; "
                "start a new run to choose differently"
            )
        if checkpoint.stage is not DiagnosisStage.FAMILY_MAPPED:
            raise DiagnosisStateError(
                "the focus selection window closed when jobs were confirmed; "
                "start a new run to choose differently"
            )
        family_map = self._derived_family_map(checkpoint)
        if family_map is None:
            raise DiagnosisStateError("this engine's comparer cannot derive a family map")
        catalogue = self._catalogue(checkpoint)
        load_by_role: dict[str, set[str]] = {}
        if family_map.non_lineage:
            # On a non-lineage run the selection names signed JOBS from the
            # map's job rows.  With zero identity matches, per-member
            # capability verdicts would be exactly the name-matching game the
            # design refuses, so the dive is scoped — and later covered — by
            # job instead.
            map_ids = {row.job_id for row in family_map.job_rows}
            outside = len(set(selection) - map_ids)
            if outside:
                raise DiagnosisStateError(
                    f"the focus selection names {outside} "
                    f"job{'' if outside == 1 else 's'} outside this run's "
                    "job map"
                )
            members_by_job = dict(catalogue.signed_job_members)
            unsigned = len([item for item in selection if item not in members_by_job])
            if unsigned:
                raise DiagnosisStateError(
                    f"the focus selection names {unsigned} "
                    f"job{'' if unsigned == 1 else 's'} the signed jobs "
                    "taxonomy does not carry"
                )
            # The coverage rule demands one job-coverage verdict per selected
            # job on its primary packet; a packet response is bounded by the
            # proposal cap, so an unpacketable selection is refused now.
            for job_id in selection:
                role = focus_job_primary_role(job_id)
                load_by_role.setdefault(role.value, set()).add(job_id)
            if any(len(jobs) > MAX_PROPOSALS_PER_PACKET for jobs in load_by_role.values()):
                raise DiagnosisStateError(
                    "this focus selection needs more job-coverage verdicts than "
                    f"one specialist packet may carry ({MAX_PROPOSALS_PER_PACKET}); "
                    "select fewer jobs"
                )
        else:
            map_ids = {row.family_id for row in family_map.rows}
            outside = len(set(selection) - map_ids)
            if outside:
                raise DiagnosisStateError(
                    f"the focus selection names {outside} "
                    f"famil{'y' if outside == 1 else 'ies'} outside this run's family map"
                )
            members_by_family = dict(catalogue.signed_family_members)
            unsigned = len([item for item in selection if item not in members_by_family])
            if unsigned:
                raise DiagnosisStateError(
                    f"the focus selection names {unsigned} "
                    f"famil{'y' if unsigned == 1 else 'ies'} the signed catalogue "
                    "carries no member contract for"
                )
            # The full-coverage rule demands one verdict per member on the
            # family's primary packet, and a packet response is bounded by the
            # proposal cap — so a selection whose per-role member load cannot fit
            # one response is refused now, not wedged later.
            for family_id in selection:
                role = focus_primary_role(family_id)
                load_by_role.setdefault(role.value, set()).update(
                    members_by_family[family_id]
                )
            if any(len(members) > MAX_PROPOSALS_PER_PACKET for members in load_by_role.values()):
                raise DiagnosisStateError(
                    "this focus selection needs more per-member verdicts than one "
                    f"specialist packet may carry ({MAX_PROPOSALS_PER_PACKET}); "
                    "select fewer families"
                )
        map_digest = canonical_json_digest(family_map.model_dump(mode="json"))
        unselected = tuple(sorted(map_ids - set(selection)))
        receipt = FocusReceipt(
            run_id=checkpoint.run_id,
            family_map_digest=map_digest,
            selected_family_ids=selection,
            unselected_family_ids=unselected,
            focus_digest=canonical_json_digest(
                {
                    "family_map_digest": map_digest,
                    "run_id": checkpoint.run_id,
                    "selected_family_ids": list(selection),
                    "unselected_family_ids": list(unselected),
                }
            ),
            confirmed_at=self._clock(),
        )
        payload = receipt.dump_for_storage()
        try:
            refuse_hostile_payload(payload)
        except HostilePayloadError as exc:
            raise DiagnosisStateError(
                "focus receipt carries content the engine refuses to retain"
            ) from exc
        artifact = self._put("focus-receipt", payload)
        updated = checkpoint.model_copy(
            update={"artifact_digests": (*checkpoint.artifact_digests, artifact)}
        )
        self._runs.save(updated, expected_head=checkpoint.canonical_digest())
        return self._view(updated).model_copy(update={"focus": receipt})

    def _focus_receipt(self, checkpoint: DiagnosisCheckpoint) -> FocusReceipt | None:
        """Load and re-validate the stored focus receipt, or ``None``.

        The stored artifact is never trusted alone: the receipt must belong to
        this run and match the family map re-derived from the stored verified
        inputs — digest and complete selected/unselected partition — or the
        typed refusal fails the consuming surface closed.
        """

        payload = self._find_kind(checkpoint, "focus-receipt")
        if payload is None:
            return None
        try:
            receipt = FocusReceipt.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored focus receipt is unreadable") from exc
        if receipt.run_id != checkpoint.run_id:
            raise DiagnosisStateError("stored focus receipt does not belong to this run")
        family_map = self._derived_family_map(checkpoint)
        if family_map is None:
            raise DiagnosisStateError("this engine's comparer cannot derive a family map")
        map_digest = canonical_json_digest(family_map.model_dump(mode="json"))
        # On a non-lineage run the receipt partitions the map's signed JOB
        # rows; on every other run, its family rows.
        if family_map.non_lineage:
            map_ids = tuple(sorted(row.job_id for row in family_map.job_rows))
        else:
            map_ids = tuple(sorted(row.family_id for row in family_map.rows))
        partition = tuple(
            sorted((*receipt.selected_family_ids, *receipt.unselected_family_ids))
        )
        if receipt.family_map_digest != map_digest or partition != map_ids:
            raise DiagnosisStateError(
                "stored focus receipt does not match this run's family map; "
                "start a new run"
            )
        return receipt

    def _require_focus(self, checkpoint: DiagnosisCheckpoint) -> FocusReceipt:
        """The focus receipt a focused run must hold before specialist work."""

        receipt = self._focus_receipt(checkpoint)
        if receipt is None:
            raise DiagnosisStateError(
                "record the family focus selection with dex-lens diagnosis focus",
                required_step=RequiredStep.CONFIRM_FOCUS,
            )
        return receipt

    def _focus_member_slice(
        self,
        focus: FocusReceipt,
        catalogue: VerifiedCatalogueSlice,
        *,
        non_lineage: bool = False,
    ) -> tuple[str, ...]:
        """The engine-derived identity slice, sorted; never host-supplied.

        On an ordinary run: the union of the selected families' signed member
        lists.  On a non-lineage run the receipt names signed jobs, so the
        slice is the union of the capabilities serving the selected jobs —
        the borrow-side comparison surface the design calls job-keyed slices.
        """

        if non_lineage:
            members_by_job = dict(catalogue.signed_job_members)
            missing_jobs = [
                item for item in focus.selected_family_ids if item not in members_by_job
            ]
            if missing_jobs:
                raise DiagnosisStateError(
                    "stored focus receipt selects a job the signed jobs "
                    "taxonomy does not carry; start a new run"
                )
            return tuple(
                sorted(
                    {
                        member
                        for job_id in focus.selected_family_ids
                        for member in members_by_job[job_id]
                    }
                )
            )
        members_by_family = dict(catalogue.signed_family_members)
        missing = [
            item for item in focus.selected_family_ids if item not in members_by_family
        ]
        if missing:
            raise DiagnosisStateError(
                "stored focus receipt selects a family the signed catalogue "
                "carries no member contract for; start a new run"
            )
        return tuple(
            sorted(
                {
                    member
                    for family_id in focus.selected_family_ids
                    for member in members_by_family[family_id]
                }
            )
        )

    def _focus_role_required_members(
        self,
        focus: FocusReceipt,
        catalogue: VerifiedCatalogueSlice,
        role: SpecialistRole,
    ) -> frozenset[str]:
        """Member ids this role's packet must give a verdict, one by one."""

        members_by_family = dict(catalogue.signed_family_members)
        return frozenset(
            member
            for family_id in focus.selected_family_ids
            if focus_primary_role(family_id) is role
            for member in members_by_family.get(family_id, ())
        )

    def _focus_role_required_jobs(
        self,
        focus: FocusReceipt,
        role: SpecialistRole,
    ) -> frozenset[str]:
        """Selected job ids this role's packet must give a coverage verdict.

        The non-lineage translation of the full-coverage rule: per-member
        capability verdicts would be the identity-matching game a non-lineage
        run honestly cannot play, so each selected job demands one validated
        job-coverage verdict on its fixed primary packet instead.
        """

        return frozenset(
            job_id
            for job_id in focus.selected_family_ids
            if focus_job_primary_role(job_id) is role
        )

    def _run_is_non_lineage(
        self,
        fingerprint: EvidenceFingerprint,
        catalogue: VerifiedCatalogueSlice,
    ) -> bool:
        """Is Dex absent from this system? The engine-computed threshold.

        The same pure derivation ``build_family_map`` and the shipped comparer
        use, so the map's classification, the packet slices, and the coverage
        rule can never disagree about which axis a run is on. The catalogue is
        no longer consulted: the question is whether Dex's own release record
        is present, not whether any of its capability names happen to coincide
        with something the person built (AGENTS.md F8).
        """

        del catalogue
        return is_non_lineage(fingerprint)

    def _require_focus_coverage(
        self,
        checkpoint: DiagnosisCheckpoint,
        proposals: tuple[ValidatedProposal, ...],
        *,
        focus: FocusReceipt,
    ) -> None:
        """Refuse a focused run holding a silent not-assessed selected member.

        The founder's rule made mechanical: every member of every selected
        family carries a verdict — an explicit proposal citation, including a
        loud dispute — before the run may compare or close.  On a non-lineage
        run the selection names signed jobs, and the same rule demands one
        job-coverage verdict per selected job.  The typed refusal names the
        count, never the content.
        """

        catalogue = self._catalogue(checkpoint)
        if self._run_is_non_lineage(self._fingerprint(checkpoint), catalogue):
            required_jobs = set(focus.selected_family_ids)
            cited_jobs = {
                item.catalogue_id
                for item in proposals
                if item.kind is ProposalKind.JOB_COVERAGE
            }
            missing_jobs = len(required_jobs - cited_jobs)
            if missing_jobs:
                raise DiagnosisStateError(
                    f"a focused diagnosis cannot continue while {missing_jobs} "
                    f"selected job{'' if missing_jobs == 1 else 's'} "
                    f"hold{'s' if missing_jobs == 1 else ''} no job-coverage "
                    "verdict; every selected job is assessed one by one"
                )
            return
        required = set(self._focus_member_slice(focus, catalogue))
        cited = {item.catalogue_id for item in proposals}
        missing = len(required - cited)
        if missing:
            raise DiagnosisStateError(
                f"a focused diagnosis cannot continue while {missing} "
                f"selected-family member{'' if missing == 1 else 's'} "
                f"hold{'s' if missing == 1 else ''} a silent not-assessed row; "
                "every member of a selected family needs a verdict"
            )

    def _work_progress(
        self,
        checkpoint: DiagnosisCheckpoint,
        family_map: FamilyMap | None,
        focus: FocusReceipt | None,
    ) -> WorkProgress | None:
        """Derive the typed live progress for a run with work in flight.

        Engine-computed on every status read from the issued queue, its
        receipts' engine-recorded timestamps, and the run checkpoint — never
        host-supplied.  The elapsed clock anchors on the analysis-planned
        checkpoint time (work persistence preserves it), so ``elapsed_seconds``
        is the only clock-dependent field.  The pace estimate is derived only
        from recorded completion timestamps: absent until one exists, so it is
        never invented — including for runs saved before receipts carried a
        timestamp — and it is an observation of pace, never a promise.
        """

        if checkpoint.stage is not DiagnosisStage.ANALYSIS_PLANNED:
            return None
        if self._analysis_mode(checkpoint) is AnalysisMode.INVENTORY_ONLY:
            return None
        queue = self._work_queue(checkpoint)
        final_by_packet = {
            receipt.packet_id: receipt
            for receipt in queue.receipts
            if receipt.status is not WorkStatus.PENDING
        }
        packets_total = len(queue.packets)
        packets_done = sum(
            1 for packet in queue.packets if packet.packet_id in final_by_packet
        )
        packets_pending = packets_total - packets_done
        started_at = checkpoint.created_at
        elapsed_seconds = max(
            0, int((self._clock() - started_at).total_seconds())
        )
        timed = tuple(
            receipt.recorded_at
            for receipt in final_by_packet.values()
            if receipt.recorded_at is not None
        )
        estimated_remaining_seconds: int | None = None
        if timed and packets_done:
            observed = max(0.0, (max(timed) - started_at).total_seconds())
            estimated_remaining_seconds = int(
                round(observed / len(timed) * packets_pending)
            )
        families: tuple[FamilyDiveProgress, ...] = ()
        if focus is not None:
            families = self._family_dive_rows(
                checkpoint, queue, focus, family_map, final_by_packet
            )
        return WorkProgress(
            packets_total=packets_total,
            packets_done=packets_done,
            packets_pending=packets_pending,
            elapsed_seconds=elapsed_seconds,
            estimated_remaining_seconds=estimated_remaining_seconds,
            families=families,
            headline=progress_headline(
                packets_total=packets_total,
                packets_done=packets_done,
                packets_pending=packets_pending,
                estimated_remaining_seconds=estimated_remaining_seconds,
                families=families,
            ),
        )

    def _family_dive_rows(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
        focus: FocusReceipt,
        family_map: FamilyMap | None,
        final_by_packet: Mapping[str, WorkReceipt],
    ) -> tuple[FamilyDiveProgress, ...]:
        """One engine-derived progress row per selected family, in map order.

        A family's dive rides its fixed primary packet: done once that packet
        holds a final receipt, running while it is the queue's next legal
        packet, queued otherwise.  ``finding_count`` counts the accepted
        proposals citing the family's signed members — the person's units,
        derived from the recorded response records, never invented.
        """

        members_by_family = dict(self._catalogue(checkpoint).signed_family_members)
        titles = (
            {row.family_id: row.title for row in family_map.rows}
            if family_map is not None
            else {}
        )
        packets_by_role = {packet.role: packet for packet in queue.packets}
        pending = queue.pending_packets()
        running_packet_id = pending[0].packet_id if pending else None
        proposals_by_packet: dict[str, list[object]] = {}
        for record in self._response_records(checkpoint):
            receipt = WorkReceipt.model_validate(record["receipt"])
            if receipt.status is WorkStatus.COMPLETED:
                proposals = record.get("proposals")
                proposals_by_packet[receipt.packet_id] = (
                    proposals if isinstance(proposals, list) else []
                )
        rows: list[FamilyDiveProgress] = []
        for family_id in focus.selected_family_ids:
            packet = packets_by_role[focus_primary_role(family_id)]
            finding_count: int | None = None
            if packet.packet_id in final_by_packet:
                state = FamilyDiveState.DONE
                members = set(members_by_family.get(family_id, ()))
                finding_count = sum(
                    1
                    for item in proposals_by_packet.get(packet.packet_id, [])
                    if isinstance(item, dict) and item.get("catalogue_id") in members
                )
            elif packet.packet_id == running_packet_id:
                state = FamilyDiveState.RUNNING
            else:
                state = FamilyDiveState.QUEUED
            rows.append(
                FamilyDiveProgress(
                    family_id=family_id,
                    title=titles.get(family_id, family_id),
                    state=state,
                    finding_count=finding_count,
                )
            )
        return tuple(rows)

    def advance(self, run_id: str) -> DiagnosisRunView:
        # Advancing mutates the persisted run, so the whole
        # load->validate->persist section holds the run's exclusive lock.
        with self._runs.exclusive(run_id):
            return self._advance_locked(run_id)

    def _advance_locked(self, run_id: str) -> DiagnosisRunView:
        checkpoint = self._load(run_id)
        if checkpoint.stage is DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis is closed; it exposes no mutation port")
        # Legacy checkpoints predate the guided queue.  Their missing mode is
        # explicitly migrated to inventory-only and retains the old direct
        # jobs-confirmed -> compared path.
        if (
            checkpoint.stage is DiagnosisStage.JOBS_CONFIRMED
            and self._analysis_mode(checkpoint) is AnalysisMode.INVENTORY_ONLY
        ):
            return self._view(self._compare_ledger(checkpoint))
        target = NEXT_STAGE[checkpoint.stage]
        handlers = {
            DiagnosisStage.SCOPE_APPROVED: self._approve_scope,
            DiagnosisStage.INTAKE_RECORDED: self._require_intake_answers,
            DiagnosisStage.CAPTURED: self._capture,
            DiagnosisStage.CATALOGUE_VERIFIED: self._verify_catalogue,
            DiagnosisStage.FAMILY_MAPPED: self._map_families,
            DiagnosisStage.JOBS_CONFIRMED: self._confirm_jobs,
            DiagnosisStage.ANALYSIS_PLANNED: self._plan_analysis,
            DiagnosisStage.ANALYSIS_COMPLETED: self._complete_analysis,
            DiagnosisStage.COMPARED: self._compare_ledger,
            DiagnosisStage.RENDERED: self._render,
            DiagnosisStage.CHECKED: self._check,
            DiagnosisStage.SAVED: self._save,
            DiagnosisStage.CLOSED: self._close,
        }
        return self._view(handlers[target](checkpoint))

    def submit(self, run_id: str, proposal: object) -> DiagnosisRunView:
        # Legacy submission mutates the persisted run, so the whole
        # load->validate->persist section holds the run's exclusive lock.
        with self._runs.exclusive(run_id):
            return self._submit_locked(run_id, proposal)

    def _submit_locked(self, run_id: str, proposal: object) -> DiagnosisRunView:
        checkpoint = self._load(run_id)
        if checkpoint.stage is DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis is closed; it exposes no mutation port")
        # A guided run accepts specialist content only through the
        # packet-bound submit_work protocol — at every stage.  Accepting an
        # unbound legacy proposal after comparison would durably retain
        # content no work receipt ever bound, so the refusal is unconditional
        # on the run's mode rather than scoped to the analysis stages.
        if self._analysis_mode(checkpoint) is not AnalysisMode.INVENTORY_ONLY:
            raise DiagnosisStateError(
                "guided analysis accepts specialist responses only through submit_work"
            )
        if checkpoint.stage in {
            DiagnosisStage.CREATED,
            DiagnosisStage.SCOPE_APPROVED,
            DiagnosisStage.CAPTURED,
        }:
            raise DiagnosisStateError(
                "specialist proposals require a captured fingerprint and verified catalogue"
            )
        typed = (
            proposal
            if isinstance(proposal, SpecialistProposal)
            else SpecialistProposal.model_validate(proposal)
        )
        # The stored proposals artifact retains this payload verbatim, so a
        # canary or an absolute path is refused before validation can accept it.
        try:
            refuse_hostile_payload(typed.model_dump(mode="json"))
        except HostilePayloadError as exc:
            raise SpecialistProposalError(
                "specialist proposal carries content the engine refuses to retain"
            ) from exc
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        validate_proposal(typed, self._proposal_context(checkpoint, fingerprint, catalogue))
        stored = [*self._proposal_payloads(checkpoint), typed.model_dump(mode="json")]
        artifact = self._put("proposals", stored)
        updated = checkpoint.model_copy(
            update={"artifact_digests": (*checkpoint.artifact_digests, artifact)}
        )
        self._runs.save(updated, expected_head=checkpoint.canonical_digest())
        return self._view(updated)

    def work(self, run_id: str) -> WorkPacket | None:
        """Return the deterministic next packet, or ``None`` when none exists.

        Inventory-only runs intentionally expose no semantic work.  Guided
        runs expose packets only from the persisted analysis-planned queue;
        reopening the engine therefore returns byte-identical packet content.
        """

        pending = self.pending_work(run_id)
        return pending[0] if pending else None

    def pending_work(self, run_id: str) -> tuple[WorkPacket, ...]:
        """Return every pending packet the host may legally answer right now.

        This is the whole issuable round, so a host can fan all of it out to
        parallel workers from one fetch instead of draining packets one at a
        time.  The set is ``WorkQueue.pending_packets()``: all pending normal
        packets while any remains, then the sceptical packet alone once every
        normal receipt is final.  Responses may be submitted in any order.
        Inventory-only runs intentionally expose no semantic work.
        """

        checkpoint = self._load(run_id)
        mode = self._analysis_mode(checkpoint)
        if mode is AnalysisMode.INVENTORY_ONLY:
            return ()
        if checkpoint.stage is not DiagnosisStage.ANALYSIS_PLANNED:
            raise DiagnosisStateError(
                "specialist work is available only after analysis planning"
            )
        queue = self._work_queue(checkpoint)
        return queue.pending_packets()

    def work_context(self, run_id: str) -> tuple[EvidenceLegendRow, ...]:
        """Return the evidence legend for this run's guided queue.

        One row per fingerprint observation, sorted by evidence token, so a
        host can cite the opaque ``evidence:``/``observation:`` identities a
        packet carries without reverse-engineering how they are minted.  The
        rows are derived from the same privacy-screened fingerprint the queue
        was issued against; inventory-only runs expose no semantic work and
        therefore no legend.
        """

        checkpoint = self._load(run_id)
        if self._analysis_mode(checkpoint) is AnalysisMode.INVENTORY_ONLY:
            return ()
        if checkpoint.stage is not DiagnosisStage.ANALYSIS_PLANNED:
            raise DiagnosisStateError(
                "specialist work is available only after analysis planning"
            )
        fingerprint = self._fingerprint(checkpoint)
        digest = fingerprint_digest_for(fingerprint)
        rows = tuple(
            EvidenceLegendRow.for_observation(
                item,
                run_id=checkpoint.run_id,
                fingerprint_digest=digest,
            )
            for item in fingerprint.observations
        )
        return tuple(sorted(rows, key=lambda row: row.evidence_id))

    def submit_work(
        self,
        run_id: str,
        packet_id: str,
        proposals: tuple[SpecialistProposal, ...] = (),
    ) -> DiagnosisRunView:
        """Validate and durably record one engine-issued packet response.

        A malformed response consumes the first attempt as a non-terminal
        ``pending`` receipt and may be retried once.  A second malformed
        response becomes terminal ``unresolved``.  Valid responses and exact
        replays are idempotent; a changed response for the same packet fails
        closed.

        Parallel fan-out is supported, so the whole load->validate->persist
        section holds the run's exclusive inter-process lock: two concurrent
        submissions serialise instead of the later save resurrecting an
        already-final packet and dropping the earlier response's records.
        """

        with self._runs.exclusive(run_id):
            return self._submit_work_locked(run_id, packet_id, proposals)

    def _submit_work_locked(
        self,
        run_id: str,
        packet_id: str,
        proposals: tuple[SpecialistProposal, ...] = (),
    ) -> DiagnosisRunView:
        checkpoint = self._load(run_id)
        if checkpoint.stage is DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis is closed; it exposes no mutation port")
        if self._analysis_mode(checkpoint) is AnalysisMode.INVENTORY_ONLY:
            raise DiagnosisStateError(
                "inventory-only diagnosis runs do not accept specialist work"
            )
        if checkpoint.stage is not DiagnosisStage.ANALYSIS_PLANNED:
            raise DiagnosisStateError(
                "specialist work is accepted only during analysis planning"
            )
        queue = self._work_queue(checkpoint)
        matches = tuple(item for item in queue.packets if item.packet_id == packet_id)
        if len(matches) != 1:
            raise WorkQueueError("packet is not in this work queue")
        packet = matches[0]
        existing = tuple(item for item in queue.receipts if item.packet_id == packet_id)
        # A final response can be replayed only when its response digest is
        # exactly the same.  We compute the candidate digest after validation
        # below; malformed replays are deliberately allowed to consume the
        # one retry so the bounded failure history remains honest.
        final_existing = next(
            (item for item in existing if item.status in {
                WorkStatus.COMPLETED,
                WorkStatus.INSUFFICIENT,
                WorkStatus.UNRESOLVED,
            }),
            None,
        )
        attempt = final_existing.attempt_count if final_existing is not None else 1 + max(
            (item.attempt_count for item in existing), default=0
        )
        if attempt > 2:
            raise WorkQueueError("packet already has a response")

        # Loading the packet context reads engine-owned artifacts and may
        # uncover tampering.  Such a failure is a run-state error, not a
        # malformed assistant response, so it must never consume a retry.
        context = self._proposal_context_for_packet(checkpoint, packet, queue)
        # The focused full-coverage rule (engine-owned run state, computed
        # outside the bounded-attempt block for the same reason): this
        # packet's role leads zero or more selected families, and its response
        # must give every member of those families a verdict, one by one.
        focus_required: frozenset[str] = frozenset()
        focus_required_jobs: frozenset[str] = frozenset()
        if (
            self._analysis_mode(checkpoint) is AnalysisMode.FOCUSED
            and packet.role is not SpecialistRole.SCEPTICAL_RECONCILER
        ):
            focus = self._require_focus(checkpoint)
            catalogue = self._catalogue(checkpoint)
            if self._run_is_non_lineage(self._fingerprint(checkpoint), catalogue):
                # Job-keyed coverage: on a non-lineage run per-member
                # capability verdicts would be the identity-matching game the
                # design refuses, so each selected job demands one validated
                # job-coverage verdict on its primary packet instead.
                focus_required_jobs = self._focus_role_required_jobs(
                    focus, packet.role
                )
            else:
                focus_required = self._focus_role_required_members(
                    focus, catalogue, packet.role
                )
        # Aggregate recommendation state is engine-owned run state, so it is
        # also computed outside the bounded-attempt block: a corrupted store
        # stays a run-state error rather than a burned retry.  The packet's
        # own previously-recorded receipts are excluded so an exact replay of
        # an already-accepted response remains idempotent.  Sceptical
        # responses can only preserve or downgrade an existing candidate, so
        # the prospective cap applies to normal packets only.
        prior_recommendations: set[str] | None = None
        prior_factor_tuples: dict[str, set[RecommendationFactors]] | None = None
        if packet.role.value != "sceptical-reconciler":
            prior_recommendations, prior_factor_tuples = self._final_recommendation_state(
                checkpoint, queue, exclude_packet_id=packet.packet_id
            )
        try:
            typed = tuple(
                item
                if isinstance(item, SpecialistProposal)
                else SpecialistProposal.model_validate(item)
                for item in proposals
            )
            # A response carrying a session canary or an absolute path is a
            # malformed specialist response: it consumes the bounded attempt
            # and is recorded as an empty rejection, never as content.
            for item in typed:
                refuse_hostile_payload(item.model_dump(mode="json"))
            if len(typed) > packet.max_proposals:
                raise SpecialistProposalError(
                    f"a work response may contain at most {packet.max_proposals} proposals"
                )
            validated = tuple(validate_proposal(item, context) for item in typed)
            if focus_required:
                # No sampling inside a chosen family: an accepted family
                # packet response gives every assigned member a verdict.  The
                # refusal names the count, never the content, and burns the
                # bounded attempt exactly like an out-of-slice citation.
                uncovered = len(
                    focus_required - {item.catalogue_id for item in validated}
                )
                if uncovered:
                    raise SpecialistProposalError(
                        f"a focused family packet response leaves {uncovered} "
                        "selected-family member"
                        f"{'' if uncovered == 1 else 's'} without a verdict; "
                        "every member of a selected family is assessed one by one"
                    )
            if focus_required_jobs:
                # No sampling across a chosen job selection either: an
                # accepted job packet response carries one job-coverage
                # verdict per assigned selected job.  Same bounded-retry
                # shape, same count-only refusal.
                covered_jobs = {
                    item.catalogue_id
                    for item in validated
                    if item.kind is ProposalKind.JOB_COVERAGE
                }
                uncovered_jobs = len(focus_required_jobs - covered_jobs)
                if uncovered_jobs:
                    raise SpecialistProposalError(
                        f"a focused job packet response leaves {uncovered_jobs} "
                        f"selected job{'' if uncovered_jobs == 1 else 's'} "
                        "without a job-coverage verdict; every selected job is "
                        "assessed one by one"
                    )
            if prior_recommendations is not None:
                prospective = prior_recommendations | {
                    item.candidate_id or ""
                    for item in validated
                    if item.kind.value == "recommendation"
                    or item.disposition.value == "worth-borrowing"
                }
                if len(prospective) > MAX_RECOMMENDATIONS:
                    # A response that would push the run past the
                    # recommendation cap is a malformed specialist response:
                    # it burns the bounded attempt and is recorded as an
                    # empty rejection, never as content.
                    raise SpecialistProposalError(
                        f"a diagnosis may recommend at most {MAX_RECOMMENDATIONS} "
                        "Dex additions"
                    )
            if prior_factor_tuples is not None:
                prospective_tuples: dict[str, set[RecommendationFactors]] = {
                    candidate: set(tuples)
                    for candidate, tuples in prior_factor_tuples.items()
                }
                for item in validated:
                    if item.candidate_id is None or item.recommendation_factors is None:
                        continue
                    prospective_tuples.setdefault(item.candidate_id, set()).add(
                        item.recommendation_factors
                    )
                if any(
                    len(tuples) > MAX_FACTOR_TUPLES_PER_CANDIDATE
                    for tuples in prospective_tuples.values()
                ):
                    # A response that would push one candidate past the
                    # disputed-baseline factor-tuple cap is a malformed
                    # specialist response: it burns the bounded attempt and is
                    # recorded as an empty rejection, never as content.
                    # Accepting it would leave the sceptical packet's
                    # candidate baseline unconstructible and wedge the run.
                    raise SpecialistProposalError(
                        "specialist responses may propose at most "
                        f"{MAX_FACTOR_TUPLES_PER_CANDIDATE} distinct recommendation "
                        "factor tuples for one candidate"
                    )
        except (TypeError, ValueError) as exc:
            status = WorkStatus.PENDING if attempt == 1 else WorkStatus.UNRESOLVED
            receipt = WorkReceipt(
                packet_id=packet.packet_id,
                packet_digest=packet.packet_digest,
                response_digest=canonical_json_digest(
                    {
                        "attempt_count": attempt,
                        "packet_digest": packet.packet_digest,
                        "status": status.value,
                    }
                ),
                status=status,
                attempt_count=attempt,
                proposal_count=0,
                recorded_at=self._clock(),
            )
            updated_queue = queue.record(receipt)
            records = self._response_records(checkpoint)
            records.append(
                {
                    "packet_id": packet.packet_id,
                    "packet_digest": packet.packet_digest,
                    "attempt_count": attempt,
                    "receipt": receipt.model_dump(mode="json"),
                    "proposals": [],
                }
            )
            self._persist_work_state(checkpoint, updated_queue, records)
            message = (
                "specialist response was rejected; one retry remains"
                if status is WorkStatus.PENDING
                else "specialist response was rejected twice and is unresolved"
            )
            raise SpecialistProposalError(message) from exc

        # Empty is a valid, explicit evidence-insufficient response.  It is a
        # final receipt rather than a silent omission.
        status = WorkStatus.INSUFFICIENT if not validated else WorkStatus.COMPLETED
        response_payload = [item.model_dump(mode="json") for item in validated]
        response_payload.sort(key=lambda item: json.dumps(item, sort_keys=True))
        response_digest = canonical_json_digest(
            {
                "attempt_count": attempt,
                "packet_digest": packet.packet_digest,
                "proposals": response_payload,
                "status": status.value,
            }
        )
        if existing and any(
            item.status in {WorkStatus.COMPLETED, WorkStatus.INSUFFICIENT, WorkStatus.UNRESOLVED}
            and item.response_digest == response_digest
            for item in existing
        ):
            return self._view(checkpoint)
        if final_existing is not None:
            raise WorkQueueError("packet already has a different response")
        # ``record`` repeats the queue's lock and retry checks after the
        # response digest has been established.
        queue.require_pending(packet_id)
        receipt = WorkReceipt(
            packet_id=packet.packet_id,
            packet_digest=packet.packet_digest,
            response_digest=response_digest,
            status=status,
            attempt_count=attempt,
            proposal_count=len(validated),
            recorded_at=self._clock(),
        )
        updated_queue = queue.record(receipt)
        records = self._response_records(checkpoint)
        records.append(
            {
                "packet_id": packet.packet_id,
                "packet_digest": packet.packet_digest,
                "attempt_count": attempt,
                "receipt": receipt.model_dump(mode="json"),
                "proposals": [item.model_dump(mode="json") for item in typed],
                "validated": response_payload,
            }
        )
        persisted = self._persist_work_state(checkpoint, updated_queue, records)
        return self._view(persisted)

    def result(self, run_id: str) -> DiagnosisResult:
        checkpoint = self._load(run_id)
        if checkpoint.stage is not DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis result is not closed")
        return self._diagnosis_result(checkpoint)

    def _load(self, run_id: str) -> DiagnosisCheckpoint:
        checkpoint = self._runs.load(run_id)
        return self._runs.load(run_id, expected_input_digest=checkpoint.input_identity)

    def _view(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisRunView:
        return DiagnosisRunView(
            run_id=checkpoint.run_id,
            stage=checkpoint.stage,
            next_action=checkpoint.next_action,
            required_step=required_step_for_stage(checkpoint.stage),
            input_identity=checkpoint.input_identity,
            approval_url=None,
        )

    def _diagnosis_input(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisInput:
        """Load and validate the content-bound input for a confirmed run.

        Inputs written before ``analysis_mode`` existed are upgraded in memory
        to inventory-only.  New inputs must still match the checkpoint's
        content identity; accepting an altered input would make the issued
        queue and its evidence bindings stale.
        """

        payload = self._find_kind(checkpoint, "diagnosis-input")
        if not isinstance(payload, dict):
            raise DiagnosisStateError(
                "diagnosis input is missing from this diagnosis checkpoint"
            )
        legacy = "analysis_mode" not in payload
        try:
            from capability_exchange.diagnosis.run import upgrade_stored_input_payload

            upgraded = upgrade_stored_input_payload(payload)
            diagnosis_input = DiagnosisInput.model_validate(upgraded)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored diagnosis input is unreadable") from exc
        if legacy:
            # The old identity was calculated over the payload without the
            # newly-added mode field.  Preserve it while making the mode
            # explicit for all subsequent decisions.
            expected_identity = canonical_json_digest(payload)
        else:
            expected_identity = diagnosis_input.identity_digest
        if checkpoint.input_identity != expected_identity:
            raise DiagnosisStateError("stored diagnosis input identity is invalid")
        return diagnosis_input

    def _run_identity(self, checkpoint: DiagnosisCheckpoint) -> RunIdentity:
        payload = self._find_kind(checkpoint, "run-identity")
        if not isinstance(payload, dict):
            raise DiagnosisStateError("run identity is missing from this diagnosis checkpoint")
        try:
            from capability_exchange.diagnosis.run import upgrade_stored_run_identity_payload

            upgraded = upgrade_stored_run_identity_payload(payload)
            return RunIdentity.model_validate(upgraded)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored run identity is unreadable") from exc

    def _analysis_mode(self, checkpoint: DiagnosisCheckpoint) -> AnalysisMode:
        """Return the persisted mode, migrating old inputs conservatively."""

        # Only a genuinely absent diagnosis-input artifact may use the
        # candidate-scope sidecar as its pre-confirmation mode authority.  If
        # an artifact exists, let every parse or identity failure propagate so
        # tampered state cannot be silently reinterpreted as compatibility.
        if self._has_kind(checkpoint, "diagnosis-input"):
            return AnalysisMode(self._diagnosis_input(checkpoint).analysis_mode)
        identity_mode = AnalysisMode(self._run_identity(checkpoint).analysis_mode)
        # The candidate-scope sidecar mirrors the digest-chain mode authority
        # before job confirmation materialises ``diagnosis-input``.  A missing
        # or contradictory sidecar must fail closed rather than downgrade a
        # guided run back to inventory-only semantics.
        candidate_scope = self._runs.load_candidate_scope(checkpoint.run_id)
        if candidate_scope is None:
            if identity_mode is AnalysisMode.GUIDED:
                raise DiagnosisStateError(
                    "candidate scope is missing for this guided diagnosis run"
                )
            return identity_mode
        if candidate_scope.analysis_mode is not identity_mode:
            raise DiagnosisStateError(
                "stored candidate scope analysis mode does not match this run"
            )
        return identity_mode

    def _require_receipt(self, checkpoint: DiagnosisCheckpoint) -> ApprovedScopeReceipt:
        receipt = self._consent.receipt_for(checkpoint.run_id)
        if receipt is not None:
            return receipt
        stored = self._find_kind(checkpoint, "scope-receipt")
        if stored is not None:
            return ApprovedScopeReceipt.model_validate(stored)
        approval = self._runs.load_scope_approval(checkpoint.run_id)
        if approval is not None:
            return approval.receipt
        raise DiagnosisStateError(
            "approve the exact scope in this chat with dex-lens diagnosis approve",
            required_step=RequiredStep.APPROVE_SCOPE,
        )

    def _advance(
        self,
        checkpoint: DiagnosisCheckpoint,
        stage: DiagnosisStage,
        *,
        artifacts: tuple[str, ...] = (),
        input_identity: str | None = None,
    ) -> DiagnosisCheckpoint:
        moved = advance_to(
            checkpoint,
            stage,
            now=self._clock(),
            artifact_digests=(*checkpoint.artifact_digests, *artifacts),
        )
        if input_identity is not None:
            moved = moved.model_copy(update={"input_identity": input_identity})
        return self._runs.save(moved, expected_head=checkpoint.canonical_digest())

    def _approve_scope(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        receipt = self._require_receipt(checkpoint)
        artifact = self._put("scope-receipt", receipt.dump_for_storage())
        identity = canonical_json_digest(
            {"engine_version": ENGINE_VERSION, "scope_digest": receipt.scope_digest}
        )
        return self._advance(
            checkpoint,
            DiagnosisStage.SCOPE_APPROVED,
            artifacts=(artifact,),
            input_identity=identity,
        )

    def _capture(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        # The recorded intake answers are re-validated before anything beyond
        # the approved listing is read; a tampered record fails closed here.
        self._intake_receipt(checkpoint)
        receipt = self._require_receipt(checkpoint)
        fingerprint = self._collector.collect(receipt)
        payload = fingerprint.model_dump(mode="json")
        # The engine cannot vouch for its injected collector.  A fingerprint
        # carrying a session canary or an absolute path is refused before any
        # byte of it is retained, and the offending value is never echoed.
        try:
            refuse_hostile_payload(payload)
        except HostilePayloadError as exc:
            raise DiagnosisStateError(
                "collected fingerprint carries content the engine refuses to retain"
            ) from exc
        artifact = self._put("fingerprint", payload)
        identity = canonical_json_digest(
            {
                "engine_version": ENGINE_VERSION,
                "fingerprint_sha256": payload_digest(payload),
                "scope_digest": receipt.scope_digest,
            }
        )
        return self._advance(
            checkpoint,
            DiagnosisStage.CAPTURED,
            artifacts=(artifact,),
            input_identity=identity,
        )

    def _verify_catalogue(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        fingerprint = self._fingerprint(checkpoint)
        loaded = self._catalogues.load(
            run_id=checkpoint.run_id,
            fingerprint_digest=fingerprint_digest_for(fingerprint),
        )
        artifact = self._put(
            "catalogue",
            {
                "capability_ids": list(loaded.capability_ids),
                "catalogue_ids": list(loaded.catalogue_ids),
                "core_release": loaded.core_release,
                "family_contract_present": loaded.family_contract_present,
                "sha256": loaded.sha256,
                "unavailable_ids": list(loaded.unavailable_ids),
                "version": loaded.version,
            },
        )
        identity = canonical_json_digest(
            {
                "catalogue_sha256": loaded.sha256,
                "engine_version": ENGINE_VERSION,
                "fingerprint_digest": fingerprint_digest_for(fingerprint),
            }
        )
        return self._advance(
            checkpoint,
            DiagnosisStage.CATALOGUE_VERIFIED,
            artifacts=(artifact,),
            input_identity=identity,
        )

    def _map_families(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        """Derive and store the pass-1 family map before any specialist work.

        The stored artifact is a digest-bound audit record only: every read
        surface re-derives the map from the stored verified inputs, and
        comparison refuses a stored map that disagrees with re-derivation —
        mirroring the RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT fix.  An engine
        wired with a comparer that cannot derive maps (injected test doubles)
        advances without the artifact, exactly like a run saved before this
        stage existed.
        """

        # Resolving the mode first keeps the guided-mode integrity checks
        # (missing or tampered candidate-scope sidecar) failing closed at this
        # advance, exactly as they did when jobs-confirmed followed catalogue
        # verification directly.
        self._analysis_mode(checkpoint)
        artifacts: tuple[str, ...] = ()
        family_map = self._derived_family_map(checkpoint)
        if family_map is not None:
            payload = family_map.model_dump(mode="json")
            try:
                refuse_hostile_payload(payload)
            except HostilePayloadError as exc:
                raise DiagnosisStateError(
                    "family map carries content the engine refuses to retain"
                ) from exc
            artifacts = (self._put("family-map", payload),)
        return self._advance(checkpoint, DiagnosisStage.FAMILY_MAPPED, artifacts=artifacts)

    def _confirm_jobs(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        receipt = self._require_receipt(checkpoint)
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        analysis_mode = self._analysis_mode(checkpoint)
        if analysis_mode is AnalysisMode.FOCUSED:
            # No receipt, no focused packets: the person's multi-select is the
            # approval and the typed refusal names the step until it exists.
            self._require_focus(checkpoint)
        diagnosis_input = DiagnosisInput(
            run_id=checkpoint.run_id,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            adapter_version=ADAPTER_VERSION,
            approved_scope_receipt=receipt,
            fingerprint_sha256=payload_digest(fingerprint.model_dump(mode="json")),
            catalogue_version=catalogue.version,
            catalogue_sha256=catalogue.sha256,
            confirmed_jobs=(),
            analysis_mode=analysis_mode.value,
            assessed_at=self._clock(),
        )
        artifact = self._put("diagnosis-input", diagnosis_input.dump_for_storage())
        return self._advance(
            checkpoint,
            DiagnosisStage.JOBS_CONFIRMED,
            artifacts=(artifact,),
            input_identity=diagnosis_input.identity_digest,
        )

    def _plan_analysis(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        """Issue and persist the exact guided queue for this pinned input."""

        mode = self._analysis_mode(checkpoint)
        if mode is AnalysisMode.INVENTORY_ONLY:
            # This branch is normally handled in ``advance`` so old runs keep
            # their direct comparison semantics.  Refuse a forged transition
            # rather than emitting an empty queue for a run that was not
            # created in guided mode.
            raise DiagnosisStateError("inventory-only diagnosis runs do not issue specialist work")
        if mode is AnalysisMode.FOCUSED:
            # A focused queue may only ever be issued against the recorded
            # selection: a run whose receipt disappeared between confirmation
            # and planning fails closed instead of issuing an unsliced queue.
            self._require_focus(checkpoint)
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        context = self._proposal_context(checkpoint, fingerprint, catalogue)
        queue = build_work_queue(context=context, mode=mode)
        queue_artifact = self._put("work-queue", queue.model_dump(mode="json"))
        # The response log is cumulative.  Keeping an explicit empty artifact
        # makes a missing/tampered log distinguishable from a pristine queue.
        responses_artifact = self._put("work-responses", [])
        audit_artifact = self._put("work-audit", queue.audit().model_dump(mode="json"))
        return self._advance(
            checkpoint,
            DiagnosisStage.ANALYSIS_PLANNED,
            artifacts=(queue_artifact, responses_artifact, audit_artifact),
        )

    def _complete_analysis(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        """Reconcile all normal work and the locked sceptical response."""

        if self._analysis_mode(checkpoint) is AnalysisMode.INVENTORY_ONLY:
            raise DiagnosisStateError("inventory-only diagnosis runs have no guided analysis")
        queue = self._work_queue(checkpoint)
        if not queue.complete():
            raise DiagnosisStateError(
                "specialist work remains before analysis can complete",
                required_step=RequiredStep.SUBMIT_WORK,
            )
        final = self._final_reconciled_proposals(checkpoint, queue)
        proposals_artifact = self._put(
            "reconciled-proposals",
            [item.model_dump(mode="json") for item in final],
        )
        return self._advance(
            checkpoint,
            DiagnosisStage.ANALYSIS_COMPLETED,
            artifacts=(proposals_artifact,),
        )

    def _final_reconciled_proposals(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
    ) -> tuple[ValidatedProposal, ...]:
        """Re-derive the final proposal set from validated response records.

        Normal reconciliation overlaid by locked sceptical results.  This is
        the one derivation both analysis completion and comparison consume, so
        the stored ``reconciled-proposals`` artifact can never become an
        authority the receipts do not support.
        """

        normal = self._normal_reconciled_proposals(checkpoint, queue)
        sceptical = self._sceptical_reconciled_proposals(checkpoint, queue)
        # A sceptical response may only refer to a baseline issued by normal
        # work.  Validation already enforces this, but retaining the set check
        # here makes a forged response log fail closed before comparison.
        normal_candidate_ids = {candidate.candidate_id for candidate in normal}
        if any(item.candidate_id not in normal_candidate_ids for item in sceptical):
            raise DiagnosisStateError(
                "sceptical work references an unknown normal candidate"
            )
        sceptical_by_candidate = {
            item.candidate_id: item
            for item in sceptical
            if item.candidate_id is not None
        }
        return tuple(
            sceptical_by_candidate.get(item.candidate_id, item)
            for item in normal
        )

    def _compare_ledger(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        # The stored family map is an audit record, never an input: comparison
        # re-derives it and refuses a stored copy that differs in any way —
        # the same discipline RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT demanded for
        # reconciled proposals.  A run with no stored map (saved before the
        # family-mapped stage existed, or driven by a comparer without the
        # derivation) proceeds: the map is re-derivable on demand, so the
        # missing audit record must not wedge a lawful run.
        stored_map = self._find_kind(checkpoint, "family-map")
        if stored_map is not None:
            derived_map = self._derived_family_map(checkpoint)
            if derived_map is None or stored_map != derived_map.model_dump(mode="json"):
                raise DiagnosisStateError(
                    "stored family map does not match the re-derived family map; "
                    "start a new run"
                )
        mode = self._analysis_mode(checkpoint)
        if mode is not AnalysisMode.INVENTORY_ONLY:
            if checkpoint.stage is not DiagnosisStage.ANALYSIS_COMPLETED:
                raise DiagnosisStateError(
                    "guided analysis must be completed before comparison"
                )
            payload = self._find_kind(checkpoint, "reconciled-proposals")
            if not isinstance(payload, list):
                raise DiagnosisStateError("reconciled specialist proposals are missing")
            # The stored artifact is an audit record, never an authority: only
            # the set re-derived from the validated response records — the
            # same derivation analysis completion performed — may reach the
            # ledger.  Shape validation alone would accept fabricated
            # recommendations no receipt supports, so any difference from the
            # re-derived set, added or dropped, is refused before comparison.
            reconciled = self._final_reconciled_proposals(
                checkpoint, self._work_queue(checkpoint)
            )
            if payload != [item.model_dump(mode="json") for item in reconciled]:
                raise DiagnosisStateError(
                    "stored reconciled proposals do not match the "
                    "responses this run recorded"
                )
        else:
            proposals = tuple(
                SpecialistProposal.model_validate(item)
                for item in self._proposal_payloads(checkpoint)
            )
            reconciled = reconcile_proposals(
                proposals,
                context=self._proposal_context(checkpoint, fingerprint, catalogue),
            )
        # The focused gates, both fail-closed: the person's recorded selection
        # must still match this run's re-derived family map, and every member
        # of every selected family must carry a verdict before comparison.
        focus_receipt: FocusReceipt | None = None
        if mode is AnalysisMode.FOCUSED:
            focus_receipt = self._require_focus(checkpoint)
            self._require_focus_coverage(checkpoint, reconciled, focus=focus_receipt)
        work_audit = None
        if mode is not AnalysisMode.INVENTORY_ONLY:
            audit_payload = self._find_kind(checkpoint, "work-audit")
            if audit_payload is None:
                # Closing without it scored the run's autonomy as zero and
                # silently stopped the incomplete-packets gate from firing, so
                # a run with unanswered packets graded as clean.
                raise DiagnosisStateError("guided analysis cannot close without its work audit")
            try:
                work_audit = WorkAudit.model_validate(audit_payload)
            except (TypeError, ValueError) as exc:
                raise DiagnosisStateError("stored work audit is unreadable") from exc
        try:
            # ``focus`` is passed only for focused runs so injected comparers
            # written before the mode existed keep their exact signature.
            focus_kwargs: dict[str, object] = (
                {"focus": focus_receipt} if focus_receipt is not None else {}
            )
            # Same shape for the intake answers: only a run that recorded them
            # passes them, so injected comparers written before the questions
            # existed keep their exact signature.
            intake_receipt = self._intake_receipt(checkpoint)
            if intake_receipt is not None:
                focus_kwargs["intake"] = intake_receipt
            ledger = self._compare.compare(
                fingerprint=fingerprint,
                catalogue=catalogue,
                jobs=(),
                proposals=reconciled,
                work_audit=work_audit,
                **focus_kwargs,
            )
        except ValidationError as exc:
            # The blanket CLI catch turned this into "not a closed typed
            # diagnosis value" — exit 2 forever, telling nobody anything.  A
            # comparer that cannot assemble a lawful ledger must surface as a
            # typed refusal naming the failing model and fields, never
            # pydantic's messages and never any value.
            raise _typed_model_refusal("comparison built", exc) from exc
        ledger_payload = ledger.model_dump(mode="json")
        # The ledger is what renders and saves.  A comparer that carried raw
        # session content into a conclusion is refused before the run can
        # render, check, or save it.
        try:
            refuse_hostile_payload(ledger_payload)
        except HostilePayloadError as exc:
            raise DiagnosisStateError(
                "comparison ledger carries content the engine refuses to retain"
            ) from exc
        artifact = self._put("ledger", ledger_payload)
        if (
            mode is AnalysisMode.INVENTORY_ONLY
            and checkpoint.stage is DiagnosisStage.JOBS_CONFIRMED
        ):
            moved = advance_inventory_to_compare(
                checkpoint,
                now=self._clock(),
                artifact_digests=(artifact,),
            )
            return self._runs.save(moved, expected_head=checkpoint.canonical_digest())
        return self._advance(checkpoint, DiagnosisStage.COMPARED, artifacts=(artifact,))

    def _render(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        self._diagnosis_result(checkpoint)
        return self._advance(checkpoint, DiagnosisStage.RENDERED)

    def _check(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        result = self._diagnosis_result(checkpoint)
        expected = canonical_fact_block(result.ledger)
        if expected not in result.render_markdown():
            raise DiagnosisStateError("report is missing exact ledger-derived facts")
        if result.report.ledger_sha256 != canonical_ledger_digest(result.ledger):
            raise DiagnosisStateError("report is missing exact ledger-derived facts")
        if ledger_appendix_errors(result.render_markdown(), result.ledger):
            raise DiagnosisStateError("report is missing the complete ledger appendix")
        return self._advance(checkpoint, DiagnosisStage.CHECKED)

    def _save(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        result = self._diagnosis_result(checkpoint)
        saved = self._reports.save_result(
            result, label=result.report.run_identity.run_id, now=self._clock()
        )
        artifact = self._put("saved-report", {"path": str(saved.path)})
        return self._advance(
            checkpoint,
            DiagnosisStage.SAVED,
            artifacts=(artifact,),
        )

    def _close(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        if self._analysis_mode(checkpoint) is AnalysisMode.FOCUSED:
            # The founder's rule holds to the last transition: a focused run
            # never closes while a selected-family member sits silently
            # not-assessed, even if earlier stages were reached another way.
            reconciled = self._final_reconciled_proposals(
                checkpoint, self._work_queue(checkpoint)
            )
            self._require_focus_coverage(
                checkpoint, reconciled, focus=self._require_focus(checkpoint)
            )
        return self._advance(checkpoint, DiagnosisStage.CLOSED)

    def _diagnosis_result(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisResult:
        try:
            ledger = ComparisonLedger.model_validate(self._find_kind(checkpoint, "ledger"))
            identity = RunIdentity.model_validate(self._find_kind(checkpoint, "run-identity"))
        except ValidationError as exc:
            raise _typed_model_refusal("this run stored", exc) from exc
        fingerprint = self._fingerprint(checkpoint)
        saved_report = self._find_kind(checkpoint, "saved-report")
        report_location = (
            str(saved_report["path"])
            if isinstance(saved_report, dict) and saved_report.get("path")
            else None
        )
        report = ReportModel.from_result(
            run_identity=identity,
            ledger=ledger,
            ledger_sha256=canonical_ledger_digest(ledger),
            limits=fingerprint.limits,
            report_location=report_location,
        )
        return DiagnosisResult(report=report, ledger=ledger)

    def _fingerprint(self, checkpoint: DiagnosisCheckpoint) -> EvidenceFingerprint:
        payload = self._find_kind(checkpoint, "fingerprint")
        if payload is None:
            raise DiagnosisStateError("fingerprint is missing from this diagnosis checkpoint")
        try:
            migrated = upgrade_stored_fingerprint_payload(payload)
            return EvidenceFingerprint.model_validate(migrated)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored evidence fingerprint is unreadable") from exc

    def _catalogue(self, checkpoint: DiagnosisCheckpoint) -> VerifiedCatalogueSlice:
        """Reload the catalogue slice, trusting only signature-derived facts.

        The stored artifact is content-addressed but not signed, so every
        security-relevant fact it carries — ``family_contract_present``
        included, which alone gates release-distance authority — is re-derived
        from the pinned signature-verified catalogue via the injected loader.
        A stored slice that disagrees with that derivation is refused with a
        typed error carrying no inspected-system content, and only the derived
        slice ever reaches the engine.
        """

        payload = self._find_kind(checkpoint, "catalogue")
        if payload is None:
            raise DiagnosisStateError(
                "verified catalogue is missing from this diagnosis checkpoint"
            )
        try:
            stored = VerifiedCatalogueSlice(
                version=int(payload["version"]),
                sha256=str(payload["sha256"]),
                catalogue_ids=tuple(payload["catalogue_ids"]),
                capability_ids=tuple(payload["capability_ids"]),
                unavailable_ids=tuple(payload.get("unavailable_ids") or ()),
                family_contract_present=bool(payload.get("family_contract_present", False)),
                core_release=(
                    str(payload["core_release"])
                    if payload.get("core_release") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DiagnosisStateError(
                "stored catalogue slice is not a closed typed payload"
            ) from exc
        derived = self._catalogues.load(
            run_id=checkpoint.run_id,
            fingerprint_digest=fingerprint_digest_for(self._fingerprint(checkpoint)),
        )
        # ``signed_identity_keys``, ``signed_family_members``, and the signed
        # job sets are deliberately absent from the stored artifact: all are
        # loader-derived from the signed envelope on every load, so the
        # equality check covers exactly the stored fields and authority stays
        # with the derived slice.
        if stored != replace(
            derived,
            signed_identity_keys=(),
            signed_family_members=(),
            signed_job_ids=(),
            signed_job_members=(),
        ):
            raise DiagnosisStateError(
                "stored catalogue facts do not match the verified catalogue; "
                "start a new run"
            )
        return derived

    def _proposal_context(
        self,
        checkpoint: DiagnosisCheckpoint,
        fingerprint: EvidenceFingerprint,
        catalogue: VerifiedCatalogueSlice,
    ) -> ProposalContext:
        digest = fingerprint_digest_for(fingerprint)
        # The authorship axis is re-derived on every context build from the
        # fingerprint plus the loader's signature-derived identity keys —
        # never accepted from a submitted proposal or a stored artifact (the
        # RISK-EXTERNAL-PASS-2026-09-07 A1 lesson).  Strength and reciprocal
        # proposals must cite at least one authored observation, directly or
        # through its minted evidence token.
        # A focused run narrows the catalogue/capability identity slice to the
        # union of the selected families' signed member lists.  The slice is
        # engine-derived here on every context build — packet issue, queue
        # re-derivation, and stored-response re-validation — so a stored queue
        # or proposal citing anything outside it is refused on load.  Keying on
        # the validated receipt (mintable only on a focused run) rather than
        # the persisted mode keeps this pure read usable while a tampered
        # diagnosis-input artifact fails closed on the mutating surfaces.
        catalogue_ids = catalogue.catalogue_ids
        capability_ids = catalogue.capability_ids
        held_ids = catalogue.unavailable_ids
        # The non-lineage threshold is re-derived here from the loader's
        # signature-derived identity keys on every context build — packet
        # issue, queue re-derivation, and stored-response re-validation — so a
        # job-coverage proposal is lawful exactly when the run's own evidence
        # says no signed identity matched, never when a stored artifact says
        # so.  On a lineage run ``job_ids`` stays empty and the kind is
        # refused outright.
        non_lineage = self._run_is_non_lineage(fingerprint, catalogue)
        focus = self._focus_receipt(checkpoint)
        if focus is not None:
            member_slice = self._focus_member_slice(
                focus, catalogue, non_lineage=non_lineage
            )
            catalogue_ids = member_slice
            capability_ids = member_slice
            held_ids = tuple(sorted(set(held_ids) & set(member_slice)))
        job_ids: tuple[str, ...] = ()
        if non_lineage:
            job_ids = (
                focus.selected_family_ids
                if focus is not None
                else catalogue.signed_job_ids
            )
        signed_keys = frozenset(catalogue.signed_identity_keys)
        evidence_ids: list[str] = []
        observation_ids: list[str] = []
        authored_evidence_ids: list[str] = []
        authored_observation_ids: list[str] = []
        for item in fingerprint.observations:
            token = mint_evidence_token(
                run_id=checkpoint.run_id,
                fingerprint_digest=digest,
                observation_key=(
                    f"{item.kind.value}:{item.identity}:{item.provenance.source_id}"
                ),
            )
            evidence_ids.append(token)
            observation_ids.append(item.observation_id)
            origin = derive_observation_origin(item, signed_identity_keys=signed_keys)
            if origin is ObservationOrigin.AUTHORED:
                authored_evidence_ids.append(token)
                authored_observation_ids.append(item.observation_id)
        return ProposalContext(
            run_id=checkpoint.run_id,
            fingerprint_digest=digest,
            catalogue_digest="sha256:" + catalogue.sha256,
            evidence_ids=tuple(evidence_ids),
            catalogue_ids=catalogue_ids,
            capability_ids=capability_ids,
            observation_ids=tuple(observation_ids),
            held_ids=held_ids,
            family_contract_present=catalogue.family_contract_present,
            authored_observation_ids=tuple(sorted(authored_observation_ids)),
            authored_evidence_ids=tuple(sorted(authored_evidence_ids)),
            job_ids=job_ids,
        )

    def _proposal_context_for_packet(
        self,
        checkpoint: DiagnosisCheckpoint,
        packet: WorkPacket,
        queue: WorkQueue,
    ) -> ProposalContext:
        """Bind proposal validation to one issued packet and its role."""

        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        base = self._proposal_context(checkpoint, fingerprint, catalogue)
        accepted: tuple[CandidateBaseline, ...] = ()
        accepted_ids: tuple[str, ...] = ()
        if packet.role.value == "sceptical-reconciler":
            normal, disputes = self._normal_reconciliation(checkpoint, queue)
            # A disputed candidate coalesces to not-assessed, but the fact of
            # the dispute is signal: it still reaches the sceptical packet as
            # a baseline carrying the proposed disposition set, so the
            # sceptical review can adjudicate it with evidence.  Candidates
            # every specialist honestly left not-assessed stay excluded.
            # The baseline's own factor-tuple bound stays as the fail-closed
            # backstop against a tampered response store: submit_work enforces
            # MAX_FACTOR_TUPLES_PER_CANDIDATE before any normal response
            # becomes final, so an honest run can no longer overflow this
            # construction.
            accepted = tuple(
                CandidateBaseline(
                    candidate_id=item.candidate_id or "",
                    kind=item.kind,
                    catalogue_id=item.catalogue_id,
                    capability_id=item.capability_id,
                    original_disposition=item.disposition,
                    recommendation_factors=item.recommendation_factors,
                    evidence_ids=item.evidence_ids,
                    observation_ids=item.observation_ids,
                    disputed_dispositions=(
                        disputes[item.candidate_id].dispositions
                        if item.candidate_id in disputes
                        else ()
                    ),
                    disputed_recommendation_factors=(
                        disputes[item.candidate_id].recommendation_factor_tuples
                        if item.candidate_id in disputes
                        else ()
                    ),
                )
                for item in normal
                if item.candidate_id is not None
                and (
                    item.disposition is not Disposition.NOT_ASSESSED
                    or item.candidate_id in disputes
                )
            )
            accepted_ids = tuple(item.candidate_id for item in accepted)
        return base.model_copy(
            update={
                "analysis_mode": AnalysisMode.GUIDED.value,
                "packet_id": packet.packet_id,
                "packet_digest": packet.packet_digest,
                "packet_role": packet.role,
                "accepted_candidate_ids": accepted_ids,
                "accepted_candidates": accepted,
            }
        )

    def _work_queue(self, checkpoint: DiagnosisCheckpoint) -> WorkQueue:
        """Load the latest queue and prove it is the queue for this input."""

        payload = self._find_kind(checkpoint, "work-queue")
        if not isinstance(payload, dict):
            raise DiagnosisStateError("stored specialist work queue is missing")
        try:
            queue = WorkQueue.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored specialist work queue is unreadable") from exc
        if queue.mode is AnalysisMode.INVENTORY_ONLY:
            raise DiagnosisStateError("stored specialist work queue has an invalid mode")
        # The rebuild below re-derives the expected queue with this run's own
        # context — for a focused run that context carries the engine-derived
        # member slice — so a stored queue whose packets came from the other
        # mode (or a different selection) fails the pinned-context comparison.
        # Every mutating entry point resolves and fail-closes on the run's
        # persisted mode before reaching here.
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        # Rebuild the expected queue with the question version each stored
        # packet was actually issued under, so a run saved before a role
        # question was sharpened still resumes: question text participates in
        # every packet digest, and comparing against a current-question
        # rebuild wedged genuine old runs forever.  The builder accepts only
        # the current wording or a listed superseded wording per role, so a
        # substituted question stays refused, and the pinned run, fingerprint,
        # catalogue, and identity sets still come from this run's context, so
        # a queue from another run still fails this comparison.
        try:
            expected = build_work_queue(
                context=self._proposal_context(checkpoint, fingerprint, catalogue),
                mode=queue.mode,
                issued_questions={
                    packet.role: packet.question for packet in queue.packets
                },
            )
        except WorkQueueError as exc:
            raise DiagnosisStateError(
                "stored specialist work queue carries a question this engine never issued"
            ) from exc
        if (
            queue.packets != expected.packets
            or queue.sceptical_packet_id != expected.sceptical_packet_id
        ):
            raise DiagnosisStateError(
                "stored specialist work queue does not match the pinned context"
            )
        self._validate_work_records(checkpoint, queue)
        return queue

    def _response_records(self, checkpoint: DiagnosisCheckpoint) -> list[dict[str, object]]:
        payload = self._find_kind(checkpoint, "work-responses")
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise DiagnosisStateError("stored specialist responses are unreadable")
        records: list[dict[str, object]] = []
        seen: set[tuple[str, int]] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise DiagnosisStateError("stored specialist responses are unreadable")
            packet_id = item.get("packet_id")
            attempt = item.get("attempt_count")
            receipt = item.get("receipt")
            proposals = item.get("proposals")
            if not isinstance(packet_id, str) or not isinstance(attempt, int):
                raise DiagnosisStateError("stored specialist responses are unreadable")
            if (packet_id, attempt) in seen:
                raise DiagnosisStateError("stored specialist responses contain a duplicate attempt")
            if not isinstance(receipt, dict) or not isinstance(proposals, list):
                raise DiagnosisStateError("stored specialist responses are unreadable")
            try:
                typed_receipt = WorkReceipt.model_validate(receipt)
            except (TypeError, ValueError) as exc:
                raise DiagnosisStateError(
                    "stored specialist response receipt is unreadable"
                ) from exc
            if (
                typed_receipt.packet_id != packet_id
                or typed_receipt.attempt_count != attempt
            ):
                raise DiagnosisStateError("stored specialist response receipt is inconsistent")
            record = dict(item)
            record["receipt"] = typed_receipt.model_dump(mode="json")
            records.append(record)
            seen.add((packet_id, attempt))
        return sorted(
            records,
            key=lambda item: (str(item["packet_id"]), int(item["attempt_count"])),
        )

    def _validate_work_records(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
    ) -> None:
        """Cross-check cumulative response artifacts against queue receipts."""

        records = self._response_records(checkpoint)
        by_key = {
            (str(item["packet_id"]), int(item["attempt_count"])): item for item in records
        }
        expected_keys = {
            (receipt.packet_id, receipt.attempt_count) for receipt in queue.receipts
        }
        if set(by_key) != expected_keys:
            raise DiagnosisStateError("stored specialist responses do not match work receipts")
        packets = {packet.packet_id: packet for packet in queue.packets}
        for receipt in queue.receipts:
            record = by_key[(receipt.packet_id, receipt.attempt_count)]
            if record.get("packet_digest") != receipt.packet_digest:
                raise DiagnosisStateError("stored specialist response packet digest is invalid")
            if record.get("receipt") != receipt.model_dump(mode="json"):
                raise DiagnosisStateError("stored specialist response receipt is invalid")
            proposals = record.get("proposals")
            if not isinstance(proposals, list):
                raise DiagnosisStateError("stored specialist response proposals are unreadable")
            if receipt.status in {WorkStatus.PENDING, WorkStatus.UNRESOLVED} and proposals:
                raise DiagnosisStateError("non-final specialist response contains proposals")
            if receipt.proposal_count != len(proposals):
                raise DiagnosisStateError("specialist response proposal count is invalid")
            if receipt.status in {WorkStatus.COMPLETED, WorkStatus.INSUFFICIENT}:
                if receipt.status is WorkStatus.INSUFFICIENT and proposals:
                    raise DiagnosisStateError("insufficient specialist response contains proposals")
                if receipt.status is WorkStatus.COMPLETED and not proposals:
                    raise DiagnosisStateError("completed specialist response is empty")
                packet = packets[receipt.packet_id]
                if receipt.status is WorkStatus.COMPLETED:
                    try:
                        typed = tuple(SpecialistProposal.model_validate(item) for item in proposals)
                        context = self._proposal_context_for_packet(checkpoint, packet, queue)
                        validated = tuple(validate_proposal(item, context) for item in typed)
                    except (TypeError, ValueError) as exc:
                        raise DiagnosisStateError(
                            "stored specialist response proposal is invalid"
                        ) from exc
                    payload = [item.model_dump(mode="json") for item in validated]
                    payload.sort(key=lambda item: json.dumps(item, sort_keys=True))
                else:
                    payload = []
                expected_digest = canonical_json_digest(
                    {
                        "attempt_count": receipt.attempt_count,
                        "packet_digest": receipt.packet_digest,
                        "proposals": payload,
                        "status": receipt.status.value,
                    }
                )
            else:
                expected_digest = canonical_json_digest(
                    {
                        "attempt_count": receipt.attempt_count,
                        "packet_digest": receipt.packet_digest,
                        "status": receipt.status.value,
                    }
                )
            if receipt.response_digest != expected_digest:
                raise DiagnosisStateError("stored specialist response digest is invalid")

    def _persist_work_state(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
        records: list[dict[str, object]],
    ) -> DiagnosisCheckpoint:
        queue_artifact = self._put("work-queue", queue.model_dump(mode="json"))
        responses_artifact = self._put("work-responses", sorted(
            records,
            key=lambda item: (str(item["packet_id"]), int(item["attempt_count"])),
        ))
        audit_artifact = self._put("work-audit", queue.audit().model_dump(mode="json"))
        updated = checkpoint.model_copy(
            update={
                "artifact_digests": (
                    *checkpoint.artifact_digests,
                    queue_artifact,
                    responses_artifact,
                    audit_artifact,
                )
            }
        )
        # Staleness backstop behind the run's exclusive lock: if the persisted
        # head moved after this operation loaded it, the save is refused with
        # a typed retryable conflict instead of resurrecting an already-final
        # packet or replacing a final response.
        return self._runs.save(updated, expected_head=checkpoint.canonical_digest())

    def _final_recommendation_state(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
        *,
        exclude_packet_id: str,
    ) -> tuple[set[str], dict[str, set[RecommendationFactors]]]:
        """Aggregate recommendation facts already final on other normal packets.

        Returns the distinct recommendation candidates plus, per candidate,
        the distinct complete factor tuples the final responses proposed —
        the exact quantities the submit-time caps must bound before another
        normal response can become a final receipt.
        """

        packets = {packet.packet_id: packet for packet in queue.packets}
        candidates: set[str] = set()
        factor_tuples: dict[str, set[RecommendationFactors]] = {}
        for record in self._response_records(checkpoint):
            receipt = WorkReceipt.model_validate(record["receipt"])
            if receipt.packet_id == exclude_packet_id:
                continue
            packet = packets.get(receipt.packet_id)
            if packet is None or packet.role.value == "sceptical-reconciler":
                continue
            if receipt.status is not WorkStatus.COMPLETED:
                continue
            proposals = record.get("proposals")
            if not isinstance(proposals, list):
                raise DiagnosisStateError(
                    "stored specialist response proposals are unreadable"
                )
            for item in proposals:
                try:
                    typed = SpecialistProposal.model_validate(item)
                except (TypeError, ValueError) as exc:
                    raise DiagnosisStateError(
                        "stored normal specialist proposal is invalid"
                    ) from exc
                if (
                    typed.kind.value == "recommendation"
                    or typed.disposition.value == "worth-borrowing"
                ):
                    candidates.add(typed.candidate_id or "")
                if typed.recommendation_factors is not None:
                    factor_tuples.setdefault(typed.candidate_id or "", set()).add(
                        typed.recommendation_factors
                    )
        return candidates, factor_tuples

    def _normal_reconciled_proposals(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
    ) -> tuple[ValidatedProposal, ...]:
        """Reconcile final normal responses before sceptical review."""

        reconciled, _disputes = self._normal_reconciliation(checkpoint, queue)
        return reconciled

    def _normal_reconciliation(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
    ) -> tuple[tuple[ValidatedProposal, ...], dict[str, _CandidateDispute]]:
        """Reconcile final normal responses, keeping each dispute's facts.

        Returns the coalesced proposal set plus, for every disputed candidate
        (conflicting dispositions or conflicting complete factor tuples), the
        set of dispositions and factor tuples the specialists actually
        proposed — so the dispute can reach the sceptical packet as a
        baseline instead of silently collapsing to a bare Unknown.
        """

        packets = {packet.packet_id: packet for packet in queue.packets}
        validated: list[ValidatedProposal] = []
        for record in self._response_records(checkpoint):
            receipt = WorkReceipt.model_validate(record["receipt"])
            packet = packets.get(receipt.packet_id)
            if packet is None or packet.role.value == "sceptical-reconciler":
                continue
            if receipt.status not in {WorkStatus.COMPLETED, WorkStatus.INSUFFICIENT}:
                continue
            proposals = record.get("proposals")
            if not isinstance(proposals, list):
                raise DiagnosisStateError("stored specialist response proposals are unreadable")
            for item in proposals:
                try:
                    validated.append(
                        validate_proposal(
                            SpecialistProposal.model_validate(item),
                            self._proposal_context_for_packet(checkpoint, packet, queue),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    raise DiagnosisStateError(
                        "stored normal specialist proposal is invalid"
                    ) from exc
        groups: dict[tuple[str, str, str, str], list[ValidatedProposal]] = {}
        for item in validated:
            key = (
                item.kind.value,
                item.catalogue_id,
                item.capability_id,
                item.candidate_id or "",
            )
            groups.setdefault(key, []).append(item)
        reconciled: list[ValidatedProposal] = []
        disputes: dict[str, _CandidateDispute] = {}
        for key in sorted(groups):
            group = sorted(groups[key], key=lambda item: (item.packet_id or "", item.reason))
            sample = group[0]
            dispositions = {item.disposition for item in group}
            factors = {item.recommendation_factors for item in group}
            recommendation_factors = next(iter(factors)) if len(factors) == 1 else None
            coverage_states = {item.job_coverage for item in group}
            job_coverage = (
                sample.job_coverage if len(coverage_states) == 1 else None
            )
            disputed = False
            if (
                len(dispositions) != 1
                or len(coverage_states) != 1
                or (
                    any(item.recommendation_factors is not None for item in group)
                    and len(factors) != 1
                )
            ):
                # The structural record of the dispute: ledger assembly keys
                # its disagreement priority on this engine-set fact, never on
                # the reason text, which is free specialist input.
                disputed = True
                disposition = Disposition.NOT_ASSESSED
                recommendation_factors = None
                job_coverage = None
                reason = (
                    JOB_DISAGREEMENT_REASON
                    if sample.kind is ProposalKind.JOB_COVERAGE
                    else disagreement_reason(dispositions)
                )
                if (
                    sample.candidate_id is not None
                    and sample.kind is ProposalKind.JOB_COVERAGE
                ):
                    # A disputed job verdict stays a loud Unknown on the job
                    # axis; it never becomes a sceptical candidate baseline —
                    # the reconciler's vocabulary is catalogue dispositions,
                    # not job verdicts, and it must not adjudicate one.
                    pass
                elif sample.candidate_id is not None:
                    disputes[sample.candidate_id] = _CandidateDispute(
                        dispositions=tuple(
                            sorted(dispositions, key=lambda item: item.value)
                        ),
                        recommendation_factor_tuples=tuple(
                            sorted(
                                {
                                    item
                                    for item in factors
                                    if item is not None
                                },
                                key=lambda item: (
                                    item.reliability_risk,
                                    item.job_relevance,
                                    item.workflow_leverage,
                                    item.evidence_strength,
                                    item.adoption_effort,
                                ),
                            )
                        ),
                    )
            else:
                disposition = sample.disposition
                reason = sorted(item.reason for item in group)[0]
            # Several agreeing specialists each citing bounded evidence is
            # normal behaviour, so this union may lawfully exceed the
            # per-proposal ceiling.  Evidence breadth is corroboration, not
            # the conclusion: keep exactly the first MAX_EVIDENCE_IDS of the
            # sorted union — deterministic, order-independent, no conclusion
            # lost — instead of letting construction below raise and wedge
            # the run with no exit.
            evidence_ids = tuple(
                sorted({token for item in group for token in item.evidence_ids})
            )[:MAX_EVIDENCE_IDS]
            observation_ids = tuple(
                sorted({token for item in group for token in item.observation_ids})
            )
            reconciled.append(
                ValidatedProposal(
                    kind=sample.kind,
                    catalogue_id=sample.catalogue_id,
                    capability_id=sample.capability_id,
                    packet_id=sample.packet_id,
                    packet_digest=sample.packet_digest,
                    candidate_id=sample.candidate_id,
                    disposition=disposition,
                    recommendation_factors=recommendation_factors,
                    job_coverage=job_coverage,
                    evidence_ids=evidence_ids,
                    reason=reason,
                    observation_ids=observation_ids,
                    disputed=disputed,
                )
            )
        # Fail-closed backstop against a tampered response store.  An honest
        # run can no longer reach this raise: submit_work enforces the same
        # cap before any normal packet's response becomes a final receipt.
        if sum(
            item.kind.value == "recommendation" or item.disposition.value == "worth-borrowing"
            for item in reconciled
        ) > MAX_RECOMMENDATIONS:
            raise SpecialistProposalError(
                f"a diagnosis may recommend at most {MAX_RECOMMENDATIONS} Dex additions"
            )
        return tuple(reconciled), disputes

    def _sceptical_reconciled_proposals(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
    ) -> tuple[ValidatedProposal, ...]:
        packet = next(
            item for item in queue.packets if item.role.value == "sceptical-reconciler"
        )
        context = self._proposal_context_for_packet(checkpoint, packet, queue)
        proposals: list[SpecialistProposal] = []
        for record in self._response_records(checkpoint):
            receipt = WorkReceipt.model_validate(record["receipt"])
            if receipt.packet_id != packet.packet_id or receipt.status not in {
                WorkStatus.COMPLETED,
                WorkStatus.INSUFFICIENT,
            }:
                continue
            payload = record.get("proposals")
            if not isinstance(payload, list):
                raise DiagnosisStateError("stored sceptical response proposals are unreadable")
            try:
                proposals.extend(SpecialistProposal.model_validate(item) for item in payload)
            except (TypeError, ValueError) as exc:
                raise DiagnosisStateError(
                    "stored sceptical specialist proposal is invalid"
                ) from exc
        if not proposals:
            return ()
        try:
            return reconcile_proposals(proposals, context=context)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored sceptical specialist proposals are invalid") from exc

    def _proposal_payloads(self, checkpoint: DiagnosisCheckpoint) -> list[object]:
        payload = self._find_kind(checkpoint, "proposals")
        if not isinstance(payload, list):
            return []
        return list(payload)

    def _artifact_root(self) -> Path:
        return self._runs.storage / "artifacts"

    def _artifact_path(self, digest: str) -> Path:
        hex_digest = digest.removeprefix("sha256:")
        path = (self._artifact_root() / f"{hex_digest}.json").resolve(strict=False)
        if path.parent != self._artifact_root().resolve(strict=False):
            raise DiagnosisStateError("diagnosis artifact escaped the run store")
        return path

    def _put(self, kind: str, payload: object) -> str:
        envelope = {"kind": kind, "payload": payload}
        digest = canonical_json_digest(envelope)
        path = self._artifact_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(envelope, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        return digest

    def _get(self, digest: str) -> dict[str, object]:
        path = self._artifact_path(digest)
        if not path.is_file():
            raise DiagnosisStateError("stored diagnosis artifact is missing")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DiagnosisStateError("stored diagnosis artifact is unreadable") from exc
        if canonical_json_digest(envelope) != digest:
            raise DiagnosisStateError("stored diagnosis artifact digest is invalid")
        if not isinstance(envelope, dict):
            raise DiagnosisStateError("stored diagnosis artifact digest is invalid")
        return envelope

    def _find_kind(self, checkpoint: DiagnosisCheckpoint, kind: str) -> object | None:
        for digest in reversed(checkpoint.artifact_digests):
            envelope = self._get(digest)
            if envelope.get("kind") == kind:
                return envelope.get("payload")
        return None

    def _has_kind(self, checkpoint: DiagnosisCheckpoint, kind: str) -> bool:
        """Return whether a digest-bound artifact of ``kind`` exists."""

        for digest in reversed(checkpoint.artifact_digests):
            if self._get(digest).get("kind") == kind:
                return True
        return False
