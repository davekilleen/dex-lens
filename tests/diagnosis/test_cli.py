"""JSON diagnosis commands talk to an injected engine, never the consent authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.concierge.test_diagnosis_consent import invented_root
from tests.concierge.test_local_server import RunningServer, envelope

from capability_exchange.concierge.consent import LocalScopeConsentAuthority
from capability_exchange.diagnosis import cli
from capability_exchange.diagnosis.cli import PrepareDiagnosisRequest, diagnosis_main
from capability_exchange.diagnosis.run import (
    NEXT_ACTION,
    DiagnosisRunView,
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.specialists import candidate_id_for
from capability_exchange.diagnosis.work import WorkQueueError

RUN_ID = "run:" + "a" * 16
CAPTURED_VIEW = DiagnosisRunView(
    run_id=RUN_ID,
    stage=DiagnosisStage.CAPTURED,
    next_action=NEXT_ACTION[DiagnosisStage.CAPTURED],
    input_identity="sha256:" + "b" * 64,
)


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass
class FakeResult:
    payload: dict[str, object]
    markdown: str = "# Diagnosis\n\nclosed\n"

    def dump_for_storage(self) -> dict[str, object]:
        return dict(self.payload)

    def render_markdown(self) -> str:
        return self.markdown


@dataclass
class FixedEngine:
    view: DiagnosisRunView
    closed_result: FakeResult | None = None

    def prepare(self, request: object) -> DiagnosisRunView:
        return self.view

    def status(self, run_id: str) -> DiagnosisRunView:
        return self.view

    def advance(self, run_id: str) -> DiagnosisRunView:
        return self.view

    def submit(self, run_id: str, proposal: object) -> DiagnosisRunView:
        return self.view

    def work(self, run_id: str) -> dict[str, object] | None:
        return {
            "packet_id": "packet:sha256:" + "a" * 64,
            "packet_digest": "sha256:" + "b" * 64,
            "role": "tools-and-integrations",
            "run_id": run_id,
            "fingerprint_digest": "sha256:" + "c" * 64,
            "catalogue_digest": "sha256:" + "d" * 64,
            "evidence_ids": [],
            "catalogue_ids": ["daily-planning"],
            "capability_ids": ["planning"],
            "observation_ids": [],
            "family_ids": [],
            "workflow_ids": [],
            "question": "What tools matter?",
            "max_attempts": 2,
            "max_proposals": 24,
        }

    def submit_work(
        self,
        run_id: str,
        packet_id: str,
        proposals: tuple[object, ...] = (),
    ) -> DiagnosisRunView:
        return self.view

    def result(self, run_id: str) -> FakeResult:
        if self.closed_result is None:
            raise DiagnosisStateError("diagnosis result is not closed")
        return self.closed_result


def fake_engine(
    view: DiagnosisRunView, result: FakeResult | None = None
) -> FixedEngine:
    return FixedEngine(view=view, closed_result=result)


@dataclass
class CountingCollector:
    calls: int = 0


@dataclass
class HarnessEngine:
    consent_authority: LocalScopeConsentAuthority
    collector: CountingCollector
    views: dict[str, DiagnosisRunView] = field(default_factory=dict)

    def prepare(self, request: PrepareDiagnosisRequest) -> DiagnosisRunView:
        roots = tuple(Path(root) for root in request.roots)
        view = self.consent_authority.prepare(candidate_roots=roots)
        self.views[view.run_id] = view
        return view

    def status(self, run_id: str) -> DiagnosisRunView:
        return self.consent_authority.view_for(run_id)

    def advance(self, run_id: str) -> DiagnosisRunView:
        if self.consent_authority.receipt_for(run_id) is None:
            raise DiagnosisStateError("approve the exact scope in the local consent surface")
        self.collector.calls += 1
        view = DiagnosisRunView(
            run_id=run_id,
            stage=DiagnosisStage.CAPTURED,
            next_action=NEXT_ACTION[DiagnosisStage.CAPTURED],
            input_identity="sha256:" + "c" * 64,
        )
        self.views[run_id] = view
        return view

    def submit(self, run_id: str, proposal: object) -> DiagnosisRunView:
        return self.status(run_id)

    def result(self, run_id: str) -> FakeResult:
        raise DiagnosisStateError("diagnosis result is not closed")


class EngineHarness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = invented_root(tmp_path)
        self.collector = CountingCollector()
        self.consent_authority = LocalScopeConsentAuthority()
        self.engine = HarnessEngine(self.consent_authority, self.collector)
        self._running = RunningServer(envelope, approved_root=self.root)
        self._running.__enter__()
        monkeypatch.setattr(cli, "build_engine", lambda: self.engine)
        cli.bind_consent_surface(self._running.session, self._running.server)

    def close(self) -> None:
        cli.reset_consent_surface()
        self._running.__exit__(None, None, None)

    def cli(self, argv: list[str]) -> SimpleNamespace:
        assert diagnosis_main(argv) == 0
        # capsys is applied by the fixture wrapper; read via a hook.
        payload = self._read_stdout()
        return SimpleNamespace(**payload)

    def approve_in_local_browser(self, run_id: str) -> None:
        assert self._running.session.diagnosis_run_id == run_id
        assert self._running.session.diagnosis_consent is self.consent_authority
        self._running.bootstrap()
        status, _, body = self._running.post("/approve")
        assert status == 200, body
        assert self.consent_authority.receipt_for(run_id) is not None

    def _read_stdout(self) -> dict[str, object]:
        raise NotImplementedError


@pytest.fixture
def engine_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> EngineHarness:
    harness = EngineHarness(tmp_path, monkeypatch)

    def read_stdout() -> dict[str, object]:
        captured = capsys.readouterr()
        return json.loads(captured.out)

    harness._read_stdout = read_stdout  # type: ignore[method-assign]
    try:
        yield harness
    finally:
        harness.close()


def test_status_prints_only_canonical_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_engine", lambda: fake_engine(CAPTURED_VIEW))
    assert diagnosis_main(["status", "--run", RUN_ID, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == CAPTURED_VIEW.dump_for_storage()


def test_prepare_reads_nothing_until_local_approval(engine_harness: EngineHarness) -> None:
    prepared = engine_harness.cli(
        ["prepare", "--root", str(engine_harness.root), "--consent-surface"]
    )
    assert prepared.stage == "created"
    assert engine_harness.collector.calls == 0
    engine_harness.approve_in_local_browser(prepared.run_id)
    engine_harness.cli(["advance", "--run", prepared.run_id])
    assert engine_harness.collector.calls == 1


def test_result_json_bytes_match_engine_dump(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = FakeResult({"closed": True, "run_id": RUN_ID, "stage": "closed"})
    engine = fake_engine(CAPTURED_VIEW, result=result)
    monkeypatch.setattr(cli, "build_engine", lambda: engine)
    expected = canonical_json_bytes(engine.result(RUN_ID).dump_for_storage())

    assert diagnosis_main(["result", "--run", RUN_ID, "--format", "json"]) == 0

    assert capsys.readouterr().out.encode("utf-8") == expected


def test_result_markdown_prints_only_canonical_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    markdown = "# Diagnosis\n\nonly this report\n"
    result = FakeResult({"closed": True}, markdown=markdown)
    monkeypatch.setattr(cli, "build_engine", lambda: fake_engine(CAPTURED_VIEW, result=result))

    assert diagnosis_main(["result", "--run", RUN_ID, "--format", "markdown"]) == 0

    captured = capsys.readouterr()
    assert captured.out == markdown
    assert captured.err == ""


def test_prepare_does_not_snapshot_or_collect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from capability_exchange.concierge.collection import ScopeSnapshot

    captured: list[object] = []
    original = ScopeSnapshot.capture

    def forbidden(*args: object, **kwargs: object) -> object:
        captured.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(ScopeSnapshot, "capture", forbidden)
    view = DiagnosisRunView(
        run_id=RUN_ID,
        stage=DiagnosisStage.CREATED,
        next_action=NEXT_ACTION[DiagnosisStage.CREATED],
    )
    monkeypatch.setattr(cli, "build_engine", lambda: fake_engine(view))
    started: list[object] = []
    monkeypatch.setattr(
        cli,
        "start_or_reuse_consent_surface",
        lambda **kwargs: started.append(kwargs) or "http://127.0.0.1:9/",
    )

    assert diagnosis_main(["prepare", "--root", str(invented_root(tmp_path))]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == RUN_ID
    assert payload["approval_url"] is None
    assert payload["stage"] == "created"
    assert captured == []
    assert started == []


def test_cli_has_no_mutation_flags_on_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_engine", lambda: fake_engine(CAPTURED_VIEW))

    assert diagnosis_main(["status", "--run", RUN_ID, "--approve"]) == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err or "is not a dex-lens diagnosis command" in err
    for banned in ("--sign", "--send", "--install", "--repair", "--modify"):
        assert banned not in err


def test_wait_without_consent_surface_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert diagnosis_main(["prepare", "--root", str(invented_root(tmp_path)), "--wait"]) == 2
    captured = capsys.readouterr()
    assert "optional local page" in captured.err
    assert captured.out == ""


def test_unknown_diagnosis_command_fails_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert diagnosis_main(["invent"]) == 2
    captured = capsys.readouterr()
    assert "is not a dex-lens diagnosis command" in captured.err
    assert "approve" in captured.err
    assert captured.out == ""


def test_chat_approve_records_receipt_without_a_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = invented_root(tmp_path)
    other = tmp_path / "other-vault"
    other.mkdir()

    assert diagnosis_main(["prepare", "--root", str(root)]) == 0
    prepared = json.loads(capsys.readouterr().out)
    run_id = prepared["run_id"]
    assert prepared["approval_url"] is None
    assert prepared["stage"] == "created"

    assert diagnosis_main(["approve", "--run", run_id, "--root", str(other)]) == 2
    refused = capsys.readouterr()
    assert "do not match this run" in refused.err
    assert refused.out == ""

    assert diagnosis_main(["approve", "--run", run_id]) == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved["run_id"] == run_id
    assert approved["stage"] == "scope-approved"

    assert diagnosis_main(["approve", "--run", run_id]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["stage"] == "scope-approved"

    assert diagnosis_main(["status", "--run", run_id, "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["stage"] == "scope-approved"


def test_work_prints_only_canonical_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = fake_engine(CAPTURED_VIEW)
    monkeypatch.setattr(cli, "build_engine", lambda: engine)
    assert diagnosis_main(["work", "--run", RUN_ID, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packet"] is not None
    assert payload["packet"]["packet_id"] == "packet:sha256:" + "a" * 64


def test_prepare_accepts_guided_analysis_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: list[object] = []

    class RecordingEngine(FixedEngine):
        def prepare(self, request: cli.PrepareDiagnosisRequest) -> DiagnosisRunView:
            captured.append(request)
            return self.view

    view = DiagnosisRunView(
        run_id=RUN_ID,
        stage=DiagnosisStage.CREATED,
        next_action=NEXT_ACTION[DiagnosisStage.CREATED],
    )
    monkeypatch.setattr(cli, "build_engine", lambda: RecordingEngine(view=view))
    root = invented_root(tmp_path)
    assert (
        diagnosis_main(
            ["prepare", "--root", str(root), "--mode", "guided-analysis"]
        )
        == 0
    )
    assert len(captured) == 1
    assert captured[0].analysis_mode.value == "guided-analysis"
    assert capsys.readouterr().out



PACKET_ID = "packet:sha256:" + "a" * 64


def _write_proposal(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_proposal(reason: str) -> dict[str, object]:
    """One structurally valid specialist proposal, so guards are what refuse it."""

    return {
        "role": "tools-and-integrations",
        "kind": "mapping",
        "run_id": RUN_ID,
        "fingerprint_digest": "sha256:" + "b" * 64,
        "catalogue_digest": "sha256:" + "d" * 64,
        "packet_id": PACKET_ID,
        "packet_digest": "sha256:" + "a" * 64,
        "catalogue_id": "daily-planning",
        "capability_id": "daily-planning",
        "candidate_id": candidate_id_for(
            kind="mapping",
            catalogue_id="daily-planning",
            capability_id="daily-planning",
        ),
        "disposition": "shared",
        "evidence_ids": ["evidence:sha256:" + "e" * 64],
        "reason": reason,
    }


def test_cli_refuses_an_unknown_proposal_field_before_the_engine_sees_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A payload the engine never sees costs no specialist attempt.

    MCP parses ahead of the engine, so the CLI must too. Otherwise the same
    bytes burn one of a packet's two attempts on one adapter and none on the
    other, and two adapters produce different durable run state.
    """

    submitted: list[object] = []

    class RecordingEngine(FixedEngine):
        def submit_work(
            self, run_id: str, packet_id: str, proposals: tuple[object, ...] = ()
        ) -> DiagnosisRunView:
            submitted.append(proposals)
            return self.view

    monkeypatch.setattr(cli, "build_engine", lambda: RecordingEngine(view=CAPTURED_VIEW))
    path = _write_proposal(tmp_path, {"note": "unknown field"})
    code = diagnosis_main(
        ["submit", "--run", RUN_ID, "--packet", "packet:sha256:" + "a" * 64,
         "--proposal", str(path)]
    )
    assert code == 2
    assert submitted == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown fields are forbidden" in captured.err


def test_cli_refuses_an_absolute_path_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    submitted: list[object] = []

    class RecordingEngine(FixedEngine):
        def submit_work(
            self, run_id: str, packet_id: str, proposals: tuple[object, ...] = ()
        ) -> DiagnosisRunView:
            submitted.append(proposals)
            return self.view

    monkeypatch.setattr(cli, "build_engine", lambda: RecordingEngine(view=CAPTURED_VIEW))
    secret = "/Users/invented/vault/People/Invented_Name.md"
    path = _write_proposal(tmp_path, _valid_proposal(f"Seen in {secret}"))
    code = diagnosis_main(
        ["submit", "--run", RUN_ID, "--packet", "packet:sha256:" + "a" * 64,
         "--proposal", str(path)]
    )
    assert code == 2
    assert submitted == []
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_cli_reports_a_work_queue_error_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class RefusingEngine(FixedEngine):
        def submit_work(
            self, run_id: str, packet_id: str, proposals: tuple[object, ...] = ()
        ) -> DiagnosisRunView:
            raise WorkQueueError("packet is not in this work queue")

    monkeypatch.setattr(cli, "build_engine", lambda: RefusingEngine(view=CAPTURED_VIEW))
    path = _write_proposal(tmp_path, _valid_proposal("an ordinary reason"))
    code = diagnosis_main(
        ["submit", "--run", RUN_ID, "--packet", PACKET_ID, "--proposal", str(path)]
    )
    assert code == 2
    assert "packet is not in this work queue" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Outbound guard: the CLI must refuse to print what the MCP adapter refuses.
# ---------------------------------------------------------------------------

PLANTED_CANARY = "INVENTED_SESSION_CANARY_NEVER_RETAIN"
PLANTED_PATH = "/Users/invented-owner/vault/note.md"
SECRET_GUIDANCE = "dex-lens: secret material is not retained on the diagnosis wire."
PATH_GUIDANCE = "dex-lens: absolute paths are not retained on the diagnosis wire."


class CanaryWorkEngine(FixedEngine):
    def work(self, run_id: str) -> dict[str, object] | None:
        packet = super().work(run_id)
        assert packet is not None
        packet["question"] = f"planted {PLANTED_CANARY} in an engine packet"
        return packet


class PathWorkEngine(FixedEngine):
    def work(self, run_id: str) -> dict[str, object] | None:
        packet = super().work(run_id)
        assert packet is not None
        packet["question"] = f"seen in {PLANTED_PATH}"
        return packet


def test_work_refuses_a_packet_carrying_the_session_canary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_engine", lambda: CanaryWorkEngine(view=CAPTURED_VIEW))

    assert diagnosis_main(["work", "--run", RUN_ID, "--json"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == SECRET_GUIDANCE + "\n"
    assert PLANTED_CANARY not in captured.out
    assert PLANTED_CANARY not in captured.err


def test_work_refuses_a_packet_carrying_an_absolute_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_engine", lambda: PathWorkEngine(view=CAPTURED_VIEW))

    assert diagnosis_main(["work", "--run", RUN_ID, "--json"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == PATH_GUIDANCE + "\n"
    assert PLANTED_PATH not in captured.out
    assert PLANTED_PATH not in captured.err


def test_submit_refuses_a_returned_view_dump_carrying_planted_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The view dump is outbound wire: what MCP submit_work refuses, submit must too."""

    hostile = FakeResult(
        {
            "note": f"planted {PLANTED_CANARY} in a stored view",
            "location": PLANTED_PATH,
        }
    )

    class HostileSubmitEngine(FixedEngine):
        def submit_work(
            self, run_id: str, packet_id: str, proposals: tuple[object, ...] = ()
        ) -> DiagnosisRunView:
            return hostile  # type: ignore[return-value]

    monkeypatch.setattr(cli, "build_engine", lambda: HostileSubmitEngine(view=CAPTURED_VIEW))
    path = _write_proposal(tmp_path, _valid_proposal("an ordinary reason"))

    code = diagnosis_main(
        ["submit", "--run", RUN_ID, "--packet", PACKET_ID, "--proposal", str(path)]
    )

    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == SECRET_GUIDANCE + "\n"
    for planted in (PLANTED_CANARY, PLANTED_PATH):
        assert planted not in captured.out
        assert planted not in captured.err


def test_result_json_refuses_a_dump_carrying_planted_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A canary or absolute path in a ledger reason never reaches result --format json."""

    result = FakeResult(
        {
            "reason": f"planted {PLANTED_CANARY} in a ledger reason",
            "location": PLANTED_PATH,
        }
    )
    monkeypatch.setattr(cli, "build_engine", lambda: fake_engine(CAPTURED_VIEW, result=result))

    assert diagnosis_main(["result", "--run", RUN_ID, "--format", "json"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == SECRET_GUIDANCE + "\n"
    for planted in (PLANTED_CANARY, PLANTED_PATH):
        assert planted not in captured.out
        assert planted not in captured.err


# ---------------------------------------------------------------------------
# Crash boundary: an unexpected exception never prints vault text.
# ---------------------------------------------------------------------------


class CrashingEngine(FixedEngine):
    def status(self, run_id: str) -> DiagnosisRunView:
        raise RuntimeError(f"boom {PLANTED_CANARY} while reading {PLANTED_PATH}")


class InterruptedEngine(FixedEngine):
    def status(self, run_id: str) -> DiagnosisRunView:
        raise KeyboardInterrupt


def _crash_log_dir(state_home: Path) -> Path:
    return state_home / "dex-lens" / "capability-bridge" / "crash-logs"


def test_an_unexpected_crash_prints_a_fixed_sentence_and_a_redacted_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setattr(cli, "build_engine", lambda: CrashingEngine(view=CAPTURED_VIEW))

    code = diagnosis_main(["status", "--run", RUN_ID, "--json"])

    assert code == 70
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == cli._CRASH_SENTENCE + "\n"
    logs = sorted(_crash_log_dir(state_home).glob("crashlog-*.json"))
    assert len(logs) == 1
    raw = logs[0].read_text(encoding="utf-8")
    for planted in (PLANTED_CANARY, PLANTED_PATH, "boom"):
        assert planted not in captured.err
        assert planted not in raw
    assert "RuntimeError" in raw


def test_keyboard_interrupt_escapes_the_crash_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setattr(cli, "build_engine", lambda: InterruptedEngine(view=CAPTURED_VIEW))

    with pytest.raises(KeyboardInterrupt):
        diagnosis_main(["status", "--run", RUN_ID, "--json"])

    assert not _crash_log_dir(state_home).exists()


def test_a_failed_crash_log_write_still_prints_only_the_fixed_sentence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the state directory should be", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocked))
    monkeypatch.setattr(cli, "build_engine", lambda: CrashingEngine(view=CAPTURED_VIEW))

    code = diagnosis_main(["status", "--run", RUN_ID, "--json"])

    assert code == 70
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == cli._CRASH_SENTENCE + "\n"
    for planted in (PLANTED_CANARY, PLANTED_PATH, "boom"):
        assert planted not in captured.err
