"""Native directory selection for the local Dex Lens doorway."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

_PICKER_PROMPT = "Choose the folder Dex Lens may consider"
_LINUX_TITLE = "Dex Lens — choose the folder it may consider"


class FolderPickerError(ValueError):
    """A native folder picker cannot safely return an approved directory."""


class ProcessResult(Protocol):
    """The small subprocess result surface used by the picker."""

    returncode: int
    stdout: str


Run = Callable[..., ProcessResult]
Which = Callable[[str], str | None]
Input = Callable[[str], str]
IsATty = Callable[[], bool]


def _existing_directory(raw: str) -> Path:
    rendered = raw.strip()
    if not rendered:
        raise FolderPickerError("Dex Lens did not return a folder")
    try:
        candidate = Path(rendered).expanduser().resolve()
    except OSError as exc:
        raise FolderPickerError("Dex Lens could not access that folder") from exc
    if not candidate.is_dir():
        raise FolderPickerError("Dex Lens needs an existing directory")
    return candidate


def _terminal_directory(raw: str) -> Path:
    try:
        values = shlex.split(raw)
    except ValueError as exc:
        raise FolderPickerError("Dex Lens could not read that folder path") from exc
    if len(values) != 1:
        raise FolderPickerError("Dex Lens needs one folder path")
    return _existing_directory(values[0])


def choose_folder(
    *,
    platform: str | None = None,
    run: Run = subprocess.run,
    which: Which = shutil.which,
    input_fn: Input = input,
    stdin_isatty: IsATty = lambda: sys.stdin.isatty(),
) -> Path | None:
    """Return one existing directory, None on cancellation, or refuse safely."""

    host = platform or sys.platform
    if host == "darwin":
        osascript = which("osascript")
        if osascript is None:
            raise FolderPickerError(
                "Choose a folder manually: macOS folder selection is unavailable"
            )
        completed = run(
            [
                osascript,
                "-e",
                f'POSIX path of (choose folder with prompt "{_PICKER_PROMPT}")',
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        return _existing_directory(completed.stdout) if completed.returncode == 0 else None

    if host == "linux":
        zenity = which("zenity")
        if zenity is not None:
            completed = run(
                [
                    zenity,
                    "--file-selection",
                    "--directory",
                    f"--title={_LINUX_TITLE}",
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            return _existing_directory(completed.stdout) if completed.returncode == 0 else None
        if not stdin_isatty():
            raise FolderPickerError(
                "Choose a folder manually: no graphical picker is available on this Linux host"
            )
        selected = input_fn(
            "Drag the folder Dex Lens may consider here, then press Return: "
        ).strip()
        return _terminal_directory(selected) if selected else None

    raise FolderPickerError(
        f"Choose a folder manually: Dex Lens has no native picker for {host!r}"
    )
