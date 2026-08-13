"""Native folder selection tests for the local Dex Lens doorway."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from capability_exchange.concierge import folder_picker


class TestFolderPicker:
    def test_macos_picker_uses_fixed_osascript_argv_and_returns_existing_directory(
        self, tmp_path: Path
    ) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout=f"{tmp_path}\n", stderr="")

        picked = folder_picker.choose_folder(
            platform="darwin", run=run, which=lambda _: "/usr/bin/osascript"
        )

        assert picked == tmp_path.resolve()
        assert calls == [
            (
                [
                    "/usr/bin/osascript",
                    "-e",
                    "POSIX path of (choose folder with prompt "
                    '"Choose the folder Dex Lens may consider")',
                ],
                {"capture_output": True, "check": False, "text": True},
            )
        ]

    def test_linux_uses_zenity_when_available(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout=f"{tmp_path}\n", stderr="")

        picked = folder_picker.choose_folder(
            platform="linux",
            run=run,
            which=lambda name: "/usr/bin/zenity" if name == "zenity" else None,
        )

        assert picked == tmp_path.resolve()
        assert calls == [
            [
                "/usr/bin/zenity",
                "--file-selection",
                "--directory",
                "--title=Dex Lens — choose the folder it may consider",
            ]
        ]

    def test_cancelled_native_picker_returns_no_path(self) -> None:
        result = folder_picker.choose_folder(
            platform="darwin",
            run=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1, stdout="", stderr="cancelled"
            ),
            which=lambda _: "/usr/bin/osascript",
        )

        assert result is None

    def test_successful_native_picker_with_no_folder_refuses(self) -> None:
        with pytest.raises(folder_picker.FolderPickerError, match="did not return a folder"):
            folder_picker.choose_folder(
                platform="darwin",
                run=lambda *_args, **_kwargs: SimpleNamespace(
                    returncode=0, stdout="\n", stderr=""
                ),
                which=lambda _: "/usr/bin/osascript",
            )

    def test_rejects_picker_output_that_is_not_an_existing_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing"
        with pytest.raises(folder_picker.FolderPickerError, match="existing directory"):
            folder_picker.choose_folder(
                platform="darwin",
                run=lambda *_args, **_kwargs: SimpleNamespace(
                    returncode=0, stdout=f"{missing}\n", stderr=""
                ),
                which=lambda _: "/usr/bin/osascript",
            )

    def test_unsupported_noninteractive_host_refuses_without_shell(self) -> None:
        with pytest.raises(folder_picker.FolderPickerError, match="Choose a folder manually"):
            folder_picker.choose_folder(
                platform="linux",
                run=lambda *_args, **_kwargs: pytest.fail("no process should start"),
                which=lambda _: None,
                input_fn=lambda _prompt: pytest.fail("must not block for input"),
                stdin_isatty=lambda: False,
            )

    def test_linux_terminal_fallback_decodes_a_dragged_shell_escaped_path(
        self, tmp_path: Path
    ) -> None:
        directory = tmp_path / "with space"
        directory.mkdir()

        picked = folder_picker.choose_folder(
            platform="linux",
            run=lambda *_args, **_kwargs: pytest.fail("no graphical picker should start"),
            which=lambda _: None,
            input_fn=lambda _prompt: str(directory).replace(" ", chr(92) + " "),
            stdin_isatty=lambda: True,
        )

        assert picked == directory.resolve()
