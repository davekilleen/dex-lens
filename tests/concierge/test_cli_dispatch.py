"""One command, two shapes, and a folder that must never look like a verb.

`dex-lens catalogue|brief|inventory` serve the skill. `dex-lens <folder>`
opens the frozen browser journey. Dispatch is by hand rather than through
argparse subparsers precisely so the second form keeps working unchanged, and
that is worth holding down: a folder silently reinterpreted as a subcommand
would fail in a way nobody would think to look for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capability_exchange.concierge import cli


class TestSubcommandDispatch:
    @pytest.mark.parametrize("name", ["catalogue", "brief", "inventory", "reports"])
    def test_a_subcommand_routes_away_from_the_browser_journey(
        self, name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        def record(argv: list[str]) -> int:
            seen.extend(argv)
            return 0

        monkeypatch.setitem(cli._SUBCOMMANDS, name, record)
        monkeypatch.setattr(
            cli, "_serve_main", lambda _argv: pytest.fail("the server must not start")
        )

        assert cli.main([name, "--flag", "value"]) == 0
        assert seen == ["--flag", "value"]

    def test_a_folder_still_opens_the_browser_journey(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        served: list[list[str]] = []
        monkeypatch.setattr(cli, "_serve_main", lambda argv: served.append(list(argv)) or 0)

        assert cli.main([str(tmp_path)]) == 0
        assert served == [[str(tmp_path)]]

    def test_a_folder_named_like_a_subcommand_is_still_a_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dispatch requires an exact match, and a path never is one."""
        folder = tmp_path / "catalogue"
        folder.mkdir()
        served: list[list[str]] = []
        monkeypatch.setattr(cli, "_serve_main", lambda argv: served.append(list(argv)) or 0)

        assert cli.main([str(folder)]) == 0
        assert served == [[str(folder)]]

    def test_no_arguments_still_reaches_the_journey_parser(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        served: list[list[str]] = []
        monkeypatch.setattr(cli, "_serve_main", lambda argv: served.append(list(argv)) or 0)

        assert cli.main([]) == 0
        assert served == [[]]

    def test_no_subcommand_name_could_ever_be_a_path(self) -> None:
        for name in cli._SUBCOMMANDS:
            assert not name.startswith(("/", "~", ".")), name
            assert "/" not in name, name
