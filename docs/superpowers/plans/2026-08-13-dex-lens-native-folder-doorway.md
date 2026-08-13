# Dex Lens native-folder doorway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Let a Mac or Linux person launch the local Dex Lens journey without typing a Vault path, while preserving the existing no-read-before-consent boundary.

**Architecture:** Add a small, platform-aware folder picker owned by the concierge layer. The CLI keeps the existing explicit-root path for technical and headless callers, adds --choose-folder for the product path, and refuses safely when no supported picker exists. The picker only returns an existing directory; the session and collector are not built until that directory has been selected.

**Tech Stack:** Python 3.11+, standard-library subprocess, pathlib, argparse, pytest, ruff.

---

## Scope boundary

This is the first independently shippable product slice: choosing an exact local folder
without teaching a person terminal path syntax. It deliberately does not create a public
download, publish a release, alter the macOS containment rule, or add Windows behaviour.
Those are separate delivery projects because each has a different safety proof and release
surface. This slice must be green before the release-bundle and website work can claim a
one-paste product doorway.

---

## File structure

- Create: src/capability_exchange/concierge/folder_picker.py — fixed-argument native picker adapter, cancellation/error vocabulary, directory validation.
- Modify: src/capability_exchange/concierge/cli.py — --choose-folder control flow and mutually exclusive root selection.
- Create: tests/concierge/test_folder_picker.py — platform picker, cancellation, path validation, no-shell tests.
- Modify: tests/concierge/test_cli.py — rootless chooser route and no-session-before-selection proof.
- Modify: README.md — explain the source-build product command and its exact privacy boundary.

### Task 1: Lock down folder-picker behaviour

**Files:**
- Create: tests/concierge/test_folder_picker.py

- [x] **Step 1: Write the failing tests**

~~~python
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
        assert calls == [(
            [
                "/usr/bin/osascript",
                "-e",
                'POSIX path of (choose folder with prompt "Choose the folder Dex Lens may consider")',
            ],
            {"capture_output": True, "check": False, "text": True},
        )]

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
        assert calls == [[
            "/usr/bin/zenity",
            "--file-selection",
            "--directory",
            "--title=Dex Lens — choose the folder it may consider",
        ]]

    def test_cancelled_native_picker_returns_no_path(self) -> None:
        result = folder_picker.choose_folder(
            platform="darwin",
            run=lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="cancelled"),
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
~~~

- [x] **Step 2: Run the new tests to verify the red state**

Run:

~~~sh
python -m pytest -q tests/concierge/test_folder_picker.py
~~~

Expected: collection fails because capability_exchange.concierge.folder_picker does not exist.

- [x] **Step 3: Implement the minimal picker**

Create src/capability_exchange/concierge/folder_picker.py:

~~~python
"""Native directory selection for the local Dex Lens doorway."""

from __future__ import annotations

import shutil
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

_PICKER_PROMPT = "Choose the folder Dex Lens may consider"
_LINUX_TITLE = "Dex Lens — choose the folder it may consider"


class FolderPickerError(ValueError):
    """A native folder picker cannot safely return an approved directory."""


Run = Callable[..., SimpleNamespace]
Which = Callable[[str], str | None]
Input = Callable[[str], str]
IsATty = Callable[[], bool]


def _existing_directory(raw: str) -> Path:
    candidate = Path(raw.strip()).expanduser().resolve()
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
            raise FolderPickerError("Choose a folder manually: macOS folder selection is unavailable")
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
        selected = input_fn("Drag the folder Dex Lens may consider here, then press Return: ").strip()
        return _terminal_directory(selected) if selected else None

    raise FolderPickerError(
        f"Choose a folder manually: Dex Lens has no native picker for {host!r}"
    )
~~~

- [x] **Step 4: Run the picker tests to verify the green state**

Run:

~~~sh
python -m pytest -q tests/concierge/test_folder_picker.py
~~~

Expected: all seven tests pass.

- [x] **Step 5: Commit the picker**

~~~sh
git add src/capability_exchange/concierge/folder_picker.py tests/concierge/test_folder_picker.py
git commit -m "Add safe native folder picker"
~~~

### Task 2: Make the product CLI use the picker without starting a session early

**Files:**
- Modify: tests/concierge/test_cli.py
- Modify: src/capability_exchange/concierge/cli.py

- [ ] **Step 1: Add the failing CLI tests**

Add these methods inside the existing TestDoorway class in tests/concierge/test_cli.py:

~~~python
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
        cli, "choose_folder", lambda: (_ for _ in ()).throw(
            cli.FolderPickerError("Choose a folder manually: unavailable")
        )
    )
    monkeypatch.setattr(
        cli,
        "session_for_roots",
        lambda _roots: pytest.fail("picker error must not create a session"),
    )

    assert cli.main(["--choose-folder", "--no-open"]) == 2

    assert "Nothing was read" in capsys.readouterr().err


def test_choose_folder_and_explicit_roots_are_rejected(
    self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--choose-folder", str(tmp_path)])

    assert raised.value.code == 2
~~~

- [ ] **Step 2: Run the focused tests to verify the red state**

Run:

~~~sh
python -m pytest -q tests/concierge/test_cli.py -k choose_folder
~~~

Expected: failures because cli.choose_folder and --choose-folder do not exist.

- [ ] **Step 3: Implement the narrow CLI branch**

Import FolderPickerError and choose_folder. Change roots from nargs plus to nargs star,
add --choose-folder, then place this immediately after parse_args:

~~~python
if args.choose_folder and args.roots:
    parser.error("--choose-folder cannot be combined with an explicit folder")
if args.choose_folder:
    try:
        selected = choose_folder()
    except FolderPickerError as exc:
        print(f"dex-lens: {exc}. Nothing was read.", file=sys.stderr)
        return 2
    if selected is None:
        print("dex-lens: No folder was selected. Nothing was read.", file=sys.stderr)
        return 0
    roots = (selected,)
else:
    roots = tuple(path.expanduser().resolve() for path in args.roots)
if not roots:
    parser.error("provide an existing folder or use --choose-folder")
invalid = tuple(path for path in roots if not path.is_dir())
if invalid:
    rendered = ", ".join(str(path) for path in invalid)
    print(
        f"dex-lens: each approved root must be an existing directory: {rendered}",
        file=sys.stderr,
    )
    return 2
~~~

Retain the existing session, local server, browser and cleanup lifecycle unchanged.

- [ ] **Step 4: Run the focused tests to verify the green state**

Run:

~~~sh
python -m pytest -q tests/concierge/test_cli.py -k choose_folder
~~~

Expected: all four chooser tests pass and the existing CLI tests remain green.

- [ ] **Step 5: Commit the CLI change**

~~~sh
git add src/capability_exchange/concierge/cli.py tests/concierge/test_cli.py
git commit -m "Add choose-folder Dex Lens launch path"
~~~

### Task 3: Describe the product command honestly

**Files:**
- Modify: README.md
- Modify: tests/concierge/test_cli.py

- [ ] **Step 1: Write the failing help assertion**

Add this method inside the existing TestDoorway class:

~~~python
def test_help_explains_the_folder_chooser_without_claiming_a_scan(
    self, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--help"])

    help_text = capsys.readouterr().out.lower()
    assert "--choose-folder" in help_text
    assert "choosing a folder does not scan it" in help_text
    assert "read-only" in help_text
~~~

- [ ] **Step 2: Run the assertion to verify the red state**

Run:

~~~sh
python -m pytest -q tests/concierge/test_cli.py::TestDoorway::test_help_explains_the_folder_chooser_without_claiming_a_scan
~~~

Expected: FAIL because the current help contains no chooser language.

- [ ] **Step 3: Update the help and README**

Set the --choose-folder help to:

~~~python
help=(
    "Open a local folder chooser before starting the private, read-only session. "
    "Choosing a folder does not scan it."
),
~~~

Replace the technical-evaluator command in README.md with:

~~~sh
.venv/bin/dex-lens --choose-folder
~~~

Immediately below it add:

~~~markdown
Dex Lens opens your computer's folder chooser. Selecting a folder only prepares the
local permission screen; it does not scan or change that folder. The screen names the
exact scope before you approve any read-only Diagnosis.
~~~

Keep the manual --no-open path command in a short technical/headless paragraph below
the product path.

- [ ] **Step 4: Run the CLI and documentation checks**

Run:

~~~sh
python -m pytest -q tests/concierge/test_cli.py
python -m pytest -q tests/test_documentation.py
~~~

Expected: both commands pass.

- [ ] **Step 5: Commit the product copy**

~~~sh
git add README.md src/capability_exchange/concierge/cli.py tests/concierge/test_cli.py
git commit -m "Document folder chooser launch"
~~~

### Task 4: Verify the doorway did not weaken trust boundaries

**Files:**
- Verify only: tests/concierge/test_cli.py
- Verify only: tests/concierge/test_local_server.py
- Verify only: tests/egress/test_m3_concierge_egress.py

- [ ] **Step 1: Run the doorway and egress checks**

Run:

~~~sh
python -m pytest -rs tests/concierge/test_cli.py tests/concierge/test_local_server.py tests/egress/test_m3_concierge_egress.py
~~~

Expected: PASS, with any documented host-specific skip printed rather than hidden.

- [ ] **Step 2: Run formatting and inventory checks**

Run:

~~~sh
ruff check src/capability_exchange/concierge tests/concierge
python scripts/check_inventory.py
git diff --check origin/main...HEAD
~~~

Expected: all commands exit zero. The inventory count remains unchanged because the
chooser is ephemeral and does not serialize, persist or transmit a Vault path.

- [ ] **Step 3: Review the final diff**

Run:

~~~sh
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git status --short
~~~

Expected: only the picker, CLI, focused tests, README and this plan have changed; no
Vault, catalogue, adaptation, contribution or containment file has been broadened.
