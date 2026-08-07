"""R1 acceptance criteria for the provisional ``Inspection`` state.

From gates.md R1, verbatim targets:

- the only exit from ``Inspection`` is explicit user confirmation;
- ``Inspection``-state objects are unrepresentable in Card, export, and
  contribution payloads (type-level exclusion, not runtime filtering);
- edit and discard are available and discard removes the data from disk;
- hostile fixture: a crafted export/contribution request referencing an
  ``Inspection``-state job id must be rejected;
- fail closed: a job with missing or corrupt state metadata is treated as
  ``Inspection`` (most restrictive).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from capability_exchange.boundary.deletion import (
    registered_deletion_paths,
    run_deletion_path,
    verify_deletion_coverage,
)
from capability_exchange.boundary.inventory import load_packaged_inventory
from capability_exchange.boundary.serialization import NoTransmissibleFieldsError
from capability_exchange.jobs import (
    ConfirmedJobExport,
    CorruptJobRecordError,
    InspectionExclusionError,
    InspectionJob,
    InspectionJobStore,
    JobBoundaries,
    JobCadence,
    JobImportance,
    JobStoreError,
    SuccessContract,
    resolve_export_request,
)

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)

CANARY_SITUATION = "CANARY-inspection-7f3a you appear to assemble a weekly report"


def make_boundaries() -> JobBoundaries:
    return JobBoundaries(
        privacy_limits=("never read the personal journal folder",),
        approval_limits=("sending anything anywhere needs fresh approval",),
        autonomy_limits=("no autonomous change of any file",),
    )


def make_inspection_job(job_id: str = "weekly-report-prep") -> InspectionJob:
    return InspectionJob(
        job_id=job_id,
        title="Possible job: prepare the weekly report",
        situation=CANARY_SITUATION,
        desired_outcome="The weekly report is ready without a scramble",
        evidence_references=("file:reports-template#snap:abc123",),
        created_at=NOW,
    )


def make_contract(job_id: str = "weekly-report-prep") -> SuccessContract:
    return SuccessContract(
        job_id=job_id,
        situation="Every Friday a report has to go out",
        desired_outcome="The report is ready by Friday noon",
        success_evidence=("the report exists before noon on Friday",),
        boundaries=make_boundaries(),
        importance=JobImportance.HIGH,
        cadence=JobCadence.WEEKLY,
        confirmed_at=NOW,
    )


def confirm_kwargs() -> dict:
    return {
        "success_evidence": ("the report exists before noon on Friday",),
        "boundaries": make_boundaries(),
        "importance": JobImportance.HIGH,
        "cadence": JobCadence.WEEKLY,
        "confirmed_at": NOW,
    }


class TestInspectionStateIsDistinct:
    def test_lifecycle_is_machine_readably_inspection(self) -> None:
        assert make_inspection_job().lifecycle == "inspection"
        assert make_contract().lifecycle == "diagnosis"

    def test_lifecycle_admits_no_other_value(self) -> None:
        with pytest.raises(ValidationError):
            InspectionJob(
                lifecycle="diagnosis",  # type: ignore[arg-type]
                job_id="weekly-report-prep",
                title="t",
                situation="s",
                desired_outcome="o",
                created_at=NOW,
            )

    def test_model_copy_cannot_change_the_lifecycle(self) -> None:
        with pytest.raises(ValueError, match="explicit\\s+user confirmation|explicit user"):
            make_inspection_job().model_copy(update={"lifecycle": "diagnosis"})

    def test_model_construct_cannot_smuggle_a_lifecycle(self) -> None:
        with pytest.raises(ValueError):
            InspectionJob.model_construct(
                lifecycle="diagnosis",
                job_id="weekly-report-prep",
                title="t",
                situation="s",
                desired_outcome="o",
                evidence_references=(),
                created_at=NOW,
            )

    def test_raw_content_shaped_evidence_reference_is_rejected(self) -> None:
        prose = (
            "these are the full contents of the file the adapter read "
            "smuggled into a reference field word by word"
        )
        with pytest.raises(ValidationError):
            InspectionJob(
                job_id="weekly-report-prep",
                title="t",
                situation="s",
                desired_outcome="o",
                evidence_references=(prose,),
                created_at=NOW,
            )


class TestConfirmationIsTheOnlyExit:
    """State-machine tests: the only exit from Inspection is explicit
    user confirmation."""

    def test_confirm_produces_a_diagnosis_contract(self, tmp_path: Path) -> None:
        store = InspectionJobStore(tmp_path)
        store.save(make_inspection_job())
        contract = store.confirm("weekly-report-prep", **confirm_kwargs())
        assert isinstance(contract, SuccessContract)
        assert contract.lifecycle == "diagnosis"
        assert contract.job_id == "weekly-report-prep"

    def test_confirm_removes_the_inspection_record_from_disk(self, tmp_path: Path) -> None:
        store = InspectionJobStore(tmp_path)
        path = store.save(make_inspection_job())
        store.confirm("weekly-report-prep", **confirm_kwargs())
        assert not path.exists()
        assert store.job_ids() == ()

    def test_editing_never_exits_inspection(self, tmp_path: Path) -> None:
        store = InspectionJobStore(tmp_path)
        store.save(make_inspection_job())
        edited = store.edit(
            "weekly-report-prep",
            title="Possible job: prepare the weekly report early",
            situation="You appear to assemble the report on Thursdays",
            desired_outcome="Report done a day early",
        )
        assert isinstance(edited, InspectionJob)
        assert edited.lifecycle == "inspection"
        assert store.load("weekly-report-prep").title.endswith("early")

    def test_edited_has_no_lifecycle_parameter(self) -> None:
        with pytest.raises(TypeError):
            make_inspection_job().edited(lifecycle="diagnosis")  # type: ignore[call-arg]

    def test_saving_and_reloading_never_exits_inspection(self, tmp_path: Path) -> None:
        store = InspectionJobStore(tmp_path)
        store.save(make_inspection_job())
        for _ in range(3):
            job = store.load("weekly-report-prep")
            assert job.lifecycle == "inspection"
            store.save(job)

    def test_failed_confirmation_leaves_the_job_in_inspection(self, tmp_path: Path) -> None:
        store = InspectionJobStore(tmp_path)
        path = store.save(make_inspection_job())
        kwargs = confirm_kwargs()
        kwargs["success_evidence"] = ()  # invalid: a contract needs a signal
        with pytest.raises(ValidationError):
            store.confirm("weekly-report-prep", **kwargs)
        assert path.exists()
        assert store.load("weekly-report-prep").lifecycle == "inspection"


class TestDiscardRemovesDataFromDisk:
    def test_discard_removes_the_bytes(self, tmp_path: Path) -> None:
        store = InspectionJobStore(tmp_path)
        path = store.save(make_inspection_job())
        assert CANARY_SITUATION.encode() in path.read_bytes()
        store.discard("weekly-report-prep")
        assert not path.exists()
        for survivor in tmp_path.rglob("*"):
            if survivor.is_file():
                assert CANARY_SITUATION.encode() not in survivor.read_bytes()
        assert store.job_ids() == ()

    def test_discarding_nothing_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(JobStoreError):
            InspectionJobStore(tmp_path).discard("never-saved")

    def test_deletion_registry_path_removes_all_inspection_jobs(
        self, tmp_path: Path
    ) -> None:
        """Wired to the M1 deletion registry: the withdrawal-drill path."""
        store = InspectionJobStore(tmp_path)
        first = store.save(make_inspection_job("job-one"))
        second = store.save(make_inspection_job("job-two"))
        removed = run_deletion_path("delete-inspection-jobs", tmp_path)
        assert set(removed) == {first, second}
        assert not first.exists() and not second.exists()

    def test_deletion_path_is_registered_and_covers_the_inventory(self) -> None:
        assert "delete-inspection-jobs" in registered_deletion_paths()
        assert verify_deletion_coverage(load_packaged_inventory()) == []


class TestTypeLevelShareExclusion:
    """Inspection-state objects are unrepresentable in Card, export, and
    contribution payloads — type-level exclusion, not runtime filtering."""

    def test_export_payload_refuses_an_inspection_job(self) -> None:
        with pytest.raises(ValidationError):
            ConfirmedJobExport(jobs=(make_inspection_job(),))  # type: ignore[arg-type]

    def test_export_payload_refuses_a_mixed_tuple(self) -> None:
        with pytest.raises(ValidationError):
            ConfirmedJobExport(
                jobs=(make_contract(), make_inspection_job())  # type: ignore[arg-type]
            )

    def test_export_payload_refuses_emptiness(self) -> None:
        with pytest.raises(ValidationError):
            ConfirmedJobExport(jobs=())

    def test_export_payload_field_type_names_only_success_contract(self) -> None:
        # The schema itself, not a filter: the only job type any sharing
        # surface may hold is SuccessContract.
        annotation = ConfirmedJobExport.model_fields["jobs"].annotation
        assert annotation == tuple[SuccessContract, ...]

    def test_inspection_job_cannot_be_transmitted_at_all(self) -> None:
        # Second wall (G2): no InspectionJob field declares sharing, so the
        # serialization boundary refuses transmission structurally.
        with pytest.raises(NoTransmissibleFieldsError):
            make_inspection_job().dump_for_transmission()

    def test_crafted_export_referencing_an_inspection_job_id_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """Hostile fixture (R1, verbatim): a crafted export/contribution
        request referencing an Inspection-state job ID must be rejected."""
        store = InspectionJobStore(tmp_path)
        store.save(make_inspection_job("crafted-target"))
        confirmed = {"weekly-report-prep": make_contract()}
        with pytest.raises(InspectionExclusionError):
            resolve_export_request(("crafted-target",), confirmed)
        with pytest.raises(InspectionExclusionError):
            resolve_export_request(("weekly-report-prep", "crafted-target"), confirmed)

    def test_unknown_and_empty_requests_are_rejected_alike(self) -> None:
        confirmed = {"weekly-report-prep": make_contract()}
        with pytest.raises(InspectionExclusionError):
            resolve_export_request(("never-existed",), confirmed)
        with pytest.raises(InspectionExclusionError):
            resolve_export_request((), confirmed)

    def test_confirmed_only_request_resolves(self) -> None:
        confirmed = {"weekly-report-prep": make_contract()}
        export = resolve_export_request(("weekly-report-prep",), confirmed)
        assert export.jobs == (confirmed["weekly-report-prep"],)

    @given(job_id=st.from_regex(r"[a-z][a-z0-9]{0,10}(-[a-z0-9]{1,5}){0,2}", fullmatch=True))
    def test_no_unconfirmed_id_ever_resolves(self, job_id: str) -> None:
        with pytest.raises(InspectionExclusionError):
            resolve_export_request((job_id,), {})


class TestCorruptStateCoercion:
    """Fail closed (R1, verbatim): a job with missing or corrupt state
    metadata is treated as Inspection (most restrictive)."""

    @staticmethod
    def _write_record(directory: Path, job_id: str, payload: dict) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"inspection-job-{job_id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    @staticmethod
    def _valid_payload(job_id: str = "weekly-report-prep") -> dict:
        return {
            "lifecycle": "inspection",
            "job_id": job_id,
            "title": "Possible job: prepare the weekly report",
            "situation": "You appear to assemble a report every week",
            "desired_outcome": "The weekly report is ready without a scramble",
            "evidence_references": ["file:reports-template#snap:abc123"],
            "created_at": "2026-08-07T12:00:00Z",
        }

    def test_missing_lifecycle_metadata_loads_as_inspection(self, tmp_path: Path) -> None:
        payload = self._valid_payload()
        del payload["lifecycle"]
        self._write_record(tmp_path, "weekly-report-prep", payload)
        job = InspectionJobStore(tmp_path).load("weekly-report-prep")
        assert job.lifecycle == "inspection"

    def test_crafted_diagnosis_claim_on_disk_loads_as_inspection(
        self, tmp_path: Path
    ) -> None:
        # Confirmation is a fresh human act, never a stored flag: a record
        # that *claims* diagnosis still loads as Inspection.
        payload = self._valid_payload()
        payload["lifecycle"] = "diagnosis"
        self._write_record(tmp_path, "weekly-report-prep", payload)
        job = InspectionJobStore(tmp_path).load("weekly-report-prep")
        assert job.lifecycle == "inspection"
        assert isinstance(job, InspectionJob)

    @given(
        corrupt=st.one_of(
            st.text(max_size=30),
            st.integers(),
            st.none(),
            st.lists(st.text(max_size=5), max_size=3),
        )
    )
    def test_any_corrupt_lifecycle_value_loads_as_inspection(
        self, corrupt: object, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        directory = tmp_path_factory.mktemp("jobs")
        payload = self._valid_payload()
        payload["lifecycle"] = corrupt
        self._write_record(directory, "weekly-report-prep", payload)
        job = InspectionJobStore(directory).load("weekly-report-prep")
        assert job.lifecycle == "inspection"

    def test_unreadable_record_is_corrupt_never_shareable(self, tmp_path: Path) -> None:
        path = tmp_path / "inspection-job-weekly-report-prep.json"
        path.write_text("{ not json at all", encoding="utf-8")
        store = InspectionJobStore(tmp_path)
        with pytest.raises(CorruptJobRecordError):
            store.load("weekly-report-prep")
        # Its id still resolves to nothing shareable (no confirmed contract).
        with pytest.raises(InspectionExclusionError):
            resolve_export_request(("weekly-report-prep",), {})

    def test_corrupt_error_never_echoes_record_contents(self, tmp_path: Path) -> None:
        secret = "CANARY-corrupt-1d9e-private-value"
        path = tmp_path / "inspection-job-weekly-report-prep.json"
        path.write_text(json.dumps({"lifecycle": "inspection", "title": secret}))
        with pytest.raises(CorruptJobRecordError) as excinfo:
            InspectionJobStore(tmp_path).load("weekly-report-prep")
        assert secret not in str(excinfo.value)


class TestLocalOnlyStorage:
    def test_stored_record_round_trips(self, tmp_path: Path) -> None:
        store = InspectionJobStore(tmp_path)
        original = make_inspection_job()
        store.save(original)
        assert store.load("weekly-report-prep") == original

    def test_store_lists_only_wellformed_record_names(self, tmp_path: Path) -> None:
        store = InspectionJobStore(tmp_path)
        store.save(make_inspection_job("job-one"))
        (tmp_path / "unrelated.json").write_text("{}", encoding="utf-8")
        assert store.job_ids() == ("job-one",)

    def test_missing_record_load_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(JobStoreError):
            InspectionJobStore(tmp_path).load("never-saved")


class TestShareExclusionBypassRoutes:
    """R1 says an Inspection-state job is *unrepresentable* in a share
    payload — that must hold on the validation-skip construction routes too
    (M2 adversarial review: ``model_construct`` previously accepted one)."""

    def test_export_model_construct_rejects_an_inspection_job(self) -> None:
        with pytest.raises(ValueError, match="confirmed"):
            ConfirmedJobExport.model_construct(jobs=(make_inspection_job(),))

    def test_export_model_construct_rejects_a_mixed_tuple(self) -> None:
        with pytest.raises(ValueError, match="confirmed"):
            ConfirmedJobExport.model_construct(
                jobs=(make_contract(), make_inspection_job())
            )

    def test_export_model_copy_rejects_an_inspection_swap(self) -> None:
        export = ConfirmedJobExport(jobs=(make_contract(),))
        with pytest.raises(ValueError, match="confirmed"):
            export.model_copy(update={"jobs": (make_inspection_job(),)})

    def test_export_model_construct_accepts_confirmed_contracts(self) -> None:
        export = ConfirmedJobExport.model_construct(jobs=(make_contract(),))
        assert export.jobs[0].lifecycle == "diagnosis"
