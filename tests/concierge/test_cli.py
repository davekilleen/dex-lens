"""The installed ``dex-lens`` doorway is narrow, local, and cleans up."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from capability_exchange.concierge import cli


class FakeSession:
    bootstrap_token = "one-time-token"

    def __init__(self) -> None:
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True


class FakeServer:
    server_port = 41234

    def __init__(self) -> None:
        self.closed = False
        self.served = False

    def serve_forever(self) -> None:
        self.served = True
        raise KeyboardInterrupt

    def server_close(self) -> None:
        self.closed = True


def install_fakes(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeSession, FakeServer]:
    session = FakeSession()
    server = FakeServer()
    monkeypatch.setattr(cli, "session_for_roots", lambda roots: session)
    monkeypatch.setattr(cli, "start_server", lambda built: server)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: True)
    return session, server


class TestDoorway:
    def test_no_open_prints_only_the_one_time_loopback_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        session, server = install_fakes(monkeypatch)

        assert cli.main(["--no-open", str(tmp_path)]) == 130

        assert capsys.readouterr().out == (
            "http://127.0.0.1:41234/?token=one-time-token\n"
        )
        assert session.terminated
        assert server.closed

    def test_browser_open_uses_only_the_loopback_bootstrap_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        opened: list[str] = []
        install_fakes(monkeypatch)
        monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))

        cli.main([str(tmp_path)])

        assert opened == ["http://127.0.0.1:41234/?token=one-time-token"]

    def test_browser_open_failure_still_closes_server_and_session(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        session, server = install_fakes(monkeypatch)

        def fail_to_open(url: str) -> bool:
            raise RuntimeError("browser backend unavailable")

        monkeypatch.setattr(cli.webbrowser, "open", fail_to_open)
        with pytest.raises(RuntimeError, match="browser backend unavailable"):
            cli.main([str(tmp_path)])

        assert session.terminated
        assert server.closed

    def test_server_setup_failure_still_terminates_session(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        session = FakeSession()
        monkeypatch.setattr(cli, "session_for_roots", lambda roots: session)

        def fail_to_bind(built: FakeSession) -> FakeServer:
            raise OSError("loopback bind unavailable")

        monkeypatch.setattr(cli, "start_server", fail_to_bind)
        with pytest.raises(OSError, match="loopback bind unavailable"):
            cli.main(["--no-open", str(tmp_path)])

        assert session.terminated

    @pytest.mark.parametrize("kind", ["missing", "file"])
    def test_non_directory_root_is_refused_before_server_start(
        self,
        kind: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = tmp_path / kind
        if kind == "file":
            root.write_text("not a directory", encoding="utf-8")
        calls = SimpleNamespace(session=0, server=0)
        monkeypatch.setattr(
            cli,
            "session_for_roots",
            lambda roots: setattr(calls, "session", calls.session + 1),
        )
        monkeypatch.setattr(
            cli,
            "start_server",
            lambda session: setattr(calls, "server", calls.server + 1),
        )

        assert cli.main(["--no-open", str(root)]) == 2

        assert calls.session == 0
        assert calls.server == 0
        assert "must be an existing directory" in capsys.readouterr().err

    def test_help_states_the_local_read_only_alpha_boundary(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Bare `--help` now answers with the welcome, so ask this doorway.

        `--choose-folder --help` is a question about the folder doorway
        itself, and is the reachable way to read its own help.
        """
        with pytest.raises(SystemExit) as raised:
            cli.main(["--choose-folder", "--help"])

        assert raised.value.code == 0
        help_text = capsys.readouterr().out.lower()
        assert "local" in help_text
        assert "read-only" in help_text
        assert "alpha" in help_text

    def test_choose_folder_offers_selected_root_only_after_picker_returns(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        session, server = install_fakes(monkeypatch)
        selected = tmp_path / "selected"
        selected.mkdir()
        offered: list[tuple[Path, ...]] = []
        monkeypatch.setattr(cli, "choose_folder", lambda: selected)
        monkeypatch.setattr(
            cli,
            "session_for_roots",
            lambda roots: offered.append(roots) or session,
        )

        assert cli.main(["--choose-folder", "--no-open"]) == 130

        assert offered == [(selected.resolve(),)]
        assert session.terminated
        assert server.closed

    def test_choose_folder_cancelled_never_builds_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "choose_folder", lambda: None)
        monkeypatch.setattr(
            cli,
            "session_for_roots",
            lambda _roots: pytest.fail("selection cancellation must not create a session"),
        )

        assert cli.main(["--choose-folder", "--no-open"]) == 0

    def test_choose_folder_error_never_builds_session(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            cli,
            "choose_folder",
            lambda: (_ for _ in ()).throw(
                cli.FolderPickerError("Choose a folder manually: unavailable")
            ),
        )
        monkeypatch.setattr(
            cli,
            "session_for_roots",
            lambda _roots: pytest.fail("picker error must not create a session"),
        )

        assert cli.main(["--choose-folder", "--no-open"]) == 2

        assert "Nothing was read" in capsys.readouterr().err

    def test_choose_folder_and_explicit_roots_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            cli.main(["--choose-folder", str(tmp_path)])

        assert raised.value.code == 2

    def test_help_explains_the_folder_chooser_without_claiming_a_scan(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as raised:
            cli.main(["--choose-folder", "--help"])

        assert raised.value.code == 0
        help_text = capsys.readouterr().out.lower()
        assert "--choose-folder" in help_text
        assert "choosing a folder does not scan it" in help_text
        assert "read-only" in help_text


def test_concierge_dispatches_diagnosis_without_opening_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[list[str]] = []
    monkeypatch.setattr(cli, "diagnosis_main", lambda args: called.append(args) or 0)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: pytest.fail("must not open a browser"))
    monkeypatch.setattr(cli, "_serve_main", lambda _argv: pytest.fail("the server must not start"))

    assert cli.main(["diagnosis", "status", "--run", "run:" + "a" * 16]) == 0
    assert called == [["status", "--run", "run:" + "a" * 16]]
