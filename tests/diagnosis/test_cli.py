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
