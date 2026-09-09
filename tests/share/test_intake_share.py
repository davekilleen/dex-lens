"""Sharing the intake answers: after the report, exact bytes, separate email.

Goal: docs/superpowers/plans/2026-09-08-dex-lens-intake-goal.md, G8-G10.
Every test was observed to fail on the tree without the commands. The send
path is the one reviewed module allowed to touch the network; every test
blocks real sockets and records what would have been sent.
"""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path

import pytest
from tests.diagnosis.test_intake import DEX_ANSWERS, _at_scope_approved
from tests.diagnosis.test_job_axis import _eight_job_catalogue
from tests.diagnosis.test_real_comparer_guided_run import RealComparerHarness
from tests.evals.stale_install_fixture import write_stale_install

from capability_exchange.diagnosis.run import DiagnosisStage
from capability_exchange.diagnosis.work import AnalysisMode
from capability_exchange.share import cli as share_cli

CANARY = "INVENTED_SESSION_CANARY_NEVER_RETAIN"


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_self: socket.socket, _address: object) -> None:
        raise AssertionError("intake sharing may only egress through urlopen doubles")

    monkeypatch.setattr(socket.socket, "connect", refuse)


class _RecordingOpener:
    def __init__(self) -> None:
        self.requests: list[tuple[str, bytes]] = []

    def __call__(self, request, timeout=None):  # noqa: ANN001, ANN201
        self.requests.append((request.full_url, request.data))

        class _Response:
            status = 200

            def __enter__(self):  # noqa: ANN204
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"{}"

        return _Response()


def _saved_run(tmp_path: Path, *, answers: dict[str, str] | None = None):
    fingerprint = write_stale_install(tmp_path / "vault", dex_present=True)
    harness = RealComparerHarness(
        tmp_path, catalogue=_eight_job_catalogue(), fingerprint=fingerprint
    )
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)
    harness.engine.intake(run_id, answers or DEX_ANSWERS)
    view = harness.engine.status(run_id)
    while view.stage is not DiagnosisStage.CLOSED:
        view = harness.engine.advance(run_id)
    return harness, run_id


def _fenced_bytes(stdout: str) -> bytes:
    match = re.search(r"---8<---\n(.*)\n--->8---", stdout, re.DOTALL)
    assert match is not None, stdout
    return match.group(1).encode("utf-8")


# --- G8: after the report, exact bytes, decline changes nothing ----------------


def test_sharing_answers_is_refused_before_the_report_is_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fingerprint = write_stale_install(tmp_path / "vault")
    harness = RealComparerHarness(
        tmp_path, catalogue=_eight_job_catalogue(), fingerprint=fingerprint
    )
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)
    harness.engine.intake(run_id, DEX_ANSWERS)
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)

    exit_code = share_cli.share_answers_main(["--run", run_id])

    assert exit_code == 2
    assert "report" in capsys.readouterr().err.lower()


def test_preview_is_the_default_and_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    harness, run_id = _saved_run(tmp_path)
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)
    opener = _RecordingOpener()
    monkeypatch.setattr(share_cli.urllib.request, "urlopen", opener)
    monkeypatch.setenv("DEX_LENS_INTAKE_URL", "https://example.invalid/intake")

    exit_code = share_cli.share_answers_main(["--run", run_id])

    assert exit_code == 0
    assert opener.requests == []
    payload = json.loads(_fenced_bytes(capsys.readouterr().out))
    assert payload["answers"]["dex-installed"] == "yes"


def test_decline_leaves_the_saved_report_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    harness, run_id = _saved_run(tmp_path)
    reports = sorted((tmp_path / "reports").rglob("*.md"))
    assert reports
    before = [path.read_bytes() for path in reports]
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)

    share_cli.share_answers_main(["--run", run_id])
    capsys.readouterr()

    assert [path.read_bytes() for path in reports] == before


def test_accepting_sends_exactly_the_previewed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    harness, run_id = _saved_run(tmp_path)
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)
    opener = _RecordingOpener()
    monkeypatch.setattr(share_cli.urllib.request, "urlopen", opener)
    monkeypatch.setenv("DEX_LENS_INTAKE_URL", "https://example.invalid/intake")

    assert share_cli.share_answers_main(["--run", run_id]) == 0
    previewed = _fenced_bytes(capsys.readouterr().out)
    assert share_cli.share_answers_main(["--run", run_id, "--yes"]) == 0

    (sent,) = opener.requests
    assert sent[0] == "https://example.invalid/intake"
    assert sent[1] == previewed


def test_without_a_configured_destination_nothing_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    harness, run_id = _saved_run(tmp_path)
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)
    opener = _RecordingOpener()
    monkeypatch.setattr(share_cli.urllib.request, "urlopen", opener)
    monkeypatch.delenv("DEX_LENS_INTAKE_URL", raising=False)

    exit_code = share_cli.share_answers_main(["--run", run_id, "--yes"])

    assert exit_code == 2
    assert opener.requests == []
    assert "nothing was sent" in capsys.readouterr().err.lower()


def test_a_planted_vault_canary_cannot_reach_the_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from datetime import UTC, datetime

    from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
    from capability_exchange.adapters.claude_code.contract import claude_code_contract
    from capability_exchange.adapters.claude_code.discovery import discover_fingerprint
    from capability_exchange.adapters.claude_code.snapshot import take_snapshot

    vault = tmp_path / "vault"
    write_stale_install(vault, dex_present=True)
    # Plant the canary into the vault before capture: a skill body carries it,
    # inside the folder the run reads.
    planted = vault / ".claude" / "skills" / "workflow-skill" / "SKILL.md"
    planted.write_text(planted.read_text() + f"\n{CANARY}\n", encoding="utf-8")
    contract = claude_code_contract((str(vault.resolve()),))
    allowlist = CanonicalAllowlist(
        contract.read_scope, denied_paths=contract.denied_paths
    )
    now = datetime(2026, 9, 8, tzinfo=UTC)
    fingerprint = discover_fingerprint(take_snapshot(allowlist, taken_at=now), collected_at=now)

    harness = RealComparerHarness(
        tmp_path, catalogue=_eight_job_catalogue(), fingerprint=fingerprint
    )
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)
    harness.engine.intake(run_id, DEX_ANSWERS)
    view = harness.engine.status(run_id)
    while view.stage is not DiagnosisStage.CLOSED:
        view = harness.engine.advance(run_id)
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)

    assert share_cli.share_answers_main(["--run", run_id]) == 0
    previewed = _fenced_bytes(capsys.readouterr().out)

    assert CANARY.encode("utf-8") not in previewed


# --- G9: the payload is the closed answer set and nothing else -----------------


def test_the_payload_carries_exactly_the_declared_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    harness, run_id = _saved_run(tmp_path)
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)

    assert share_cli.share_answers_main(["--run", run_id]) == 0
    payload = json.loads(_fenced_bytes(capsys.readouterr().out))

    assert sorted(payload) == ["answers", "lens_version", "project_link", "submitted_at"]
    assert sorted(payload["answers"]) == sorted(DEX_ANSWERS)
    rendered = json.dumps(payload)
    assert "email" not in rendered
    assert "/vault" not in rendered


# --- G10: email is a separate choice and stays out of every artifact -----------


def test_newsletter_is_its_own_command_and_the_email_stays_out_of_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    harness, run_id = _saved_run(tmp_path)
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)
    opener = _RecordingOpener()
    monkeypatch.setattr(share_cli.urllib.request, "urlopen", opener)
    email = "person@example.invalid"

    assert share_cli.newsletter_main([email]) == 0  # preview only
    assert opener.requests == []
    assert email in capsys.readouterr().out
    assert share_cli.newsletter_main([email, "--yes"]) == 0

    (sent,) = opener.requests
    assert sent[0] == share_cli.NEWSLETTER_URL
    assert email.encode("utf-8") in sent[1]

    # The address appears in no run artifact and no saved report.
    for path in sorted(tmp_path.rglob("*")):
        if path.is_file():
            assert email.encode("utf-8") not in path.read_bytes(), path


def test_the_intake_payload_never_carries_the_email_even_when_both_are_shared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    harness, run_id = _saved_run(tmp_path)
    monkeypatch.setattr(share_cli, "build_engine", lambda: harness.engine)
    opener = _RecordingOpener()
    monkeypatch.setattr(share_cli.urllib.request, "urlopen", opener)
    monkeypatch.setenv("DEX_LENS_INTAKE_URL", "https://example.invalid/intake")
    email = "person@example.invalid"

    assert share_cli.share_answers_main(["--run", run_id, "--yes"]) == 0
    assert share_cli.newsletter_main([email, "--yes"]) == 0

    intake_request, newsletter_request = opener.requests
    assert email.encode("utf-8") not in intake_request[1]
    assert email.encode("utf-8") in newsletter_request[1]


# --- the newsletter goes to the site's one real doorway -------------------------


def test_the_newsletter_destination_is_the_site_s_live_subscribe_endpoint() -> None:
    """Found preparing the 2026-09-09 release: the constant pointed at
    `heydex.ai/lens/newsletter`, a page that has never existed. The heydex.ai
    site already has one subscribe doorway its own signup form posts to, it
    needs no key, and Lens uses exactly that."""

    assert (
        share_cli.NEWSLETTER_URL
        == "https://api.heydex.ai/api/newsletter/subscribe"
    )


def test_the_newsletter_payload_is_email_and_source_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The doorway reads `email` and `source` and nothing else, so that is
    exactly what Lens sends — the preview promises "nothing else" and must
    stay literally true."""

    assert share_cli.newsletter_main(["person@example.invalid"]) == 0
    payload = json.loads(_fenced_bytes(capsys.readouterr().out))

    assert sorted(payload) == ["email", "source"]
    assert payload["source"] == "dex-lens"
