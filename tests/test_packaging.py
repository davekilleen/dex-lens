"""The wheel must contain the data files the package reads at runtime.

Two files under ``src/`` are not Python and are loaded at import or at
inspection time:

- ``boundary/data_inventory.yaml`` — the G2 field inventory. Missing, the
  package does not import at all.
- ``adapters/claude_code/profiles/claude_code_containment.sb`` — the macOS
  sandbox profile. Missing, ``MacOSStrategy.availability()`` is False, the
  deep adapter refuses honestly, and (before the conformance gate learned to
  require OS enforcement) CI went green having proved nothing.

Neither was declared as package data, so a wheel built from this project
silently omitted both. Nothing caught it because CI installs with
``pip install -e .``, which reads them straight from the source tree.

These tests build a real wheel — the artifact, not the editable shim — and
look inside it. The exhaustive test is the one that matters: it derives its
expectations from what is actually in ``src/``, so a data file added later
without a matching ``[tool.setuptools.package-data]`` entry fails here
rather than in someone's install (HANDOFF 5.5: prefer the check that cannot
be forgotten).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from os import environ
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_PACKAGE = "capability_exchange"

#: Named explicitly so the two files the audit found are asserted by name and
#: not only by the generated rule below.
REQUIRED_DATA_FILES = (
    f"{_PACKAGE}/boundary/data_inventory.yaml",
    f"{_PACKAGE}/adapters/claude_code/profiles/claude_code_containment.sb",
)

_BUILD_SCRIPT = """
import sys
from setuptools import build_meta

sys.stdout.write(build_meta.build_wheel(sys.argv[1]))
"""


def _data_files_in_source_tree() -> tuple[str, ...]:
    """Every non-Python file under the package, as a wheel-relative path."""
    return tuple(
        sorted(
            str(path.relative_to(_SRC))
            for path in (_SRC / _PACKAGE).rglob("*")
            if path.is_file()
            and path.suffix != ".py"
            and "__pycache__" not in path.parts
            and not path.name.endswith(".pyc")
        )
    )


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A wheel built from a clean copy of this project.

    Built from a copy so the build leaves no ``build/`` or ``*.egg-info`` in
    the working tree, and through the PEP 517 hook directly so it needs
    neither the network nor build isolation.
    """
    pytest.importorskip(
        "setuptools",
        reason=(
            "setuptools is the build backend and a declared dev dependency; "
            "without it the wheel-contents gate cannot run and the packaging "
            "of the sandbox profile and data inventory is UNPROVEN here"
        ),
    )
    project = tmp_path_factory.mktemp("wheel-build") / "project"
    project.mkdir()
    shutil.copytree(_SRC, project / "src")
    for name in ("pyproject.toml", "README.md"):
        shutil.copy(_REPO_ROOT / name, project / name)
    output = project / "dist"
    output.mkdir()

    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _BUILD_SCRIPT, str(output)],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"wheel build failed:\n{completed.stderr}"
    return output / completed.stdout.strip().splitlines()[-1]


@pytest.fixture(scope="module")
def wheel_contents(built_wheel: Path) -> frozenset[str]:
    """Names inside the wheel artifact, rather than the editable checkout."""
    with zipfile.ZipFile(built_wheel) as archive:
        return frozenset(archive.namelist())


def test_g2_wheel_ships_the_data_inventory(wheel_contents: frozenset[str]) -> None:
    assert REQUIRED_DATA_FILES[0] in wheel_contents


def test_g1_wheel_ships_the_macos_containment_profile(
    wheel_contents: frozenset[str],
) -> None:
    assert REQUIRED_DATA_FILES[1] in wheel_contents


def test_g1_wheel_ships_every_data_file_the_source_tree_has(
    wheel_contents: frozenset[str],
) -> None:
    """No non-Python file may exist under ``src/`` without reaching the wheel.

    A data file the package reads but the wheel omits does not fail loudly:
    it degrades a gate into an honest refusal, which is exactly the shape of
    failure that hides.
    """
    expected = _data_files_in_source_tree()
    assert expected, "the packaging gate must have something to assert about"
    missing = sorted(name for name in expected if name not in wheel_contents)
    assert not missing, (
        f"{len(missing)} data file(s) exist under src/ but are absent from the "
        f"wheel: {missing}. Add a [tool.setuptools.package-data] entry for each."
    )


def test_g1_named_data_files_still_exist_where_the_code_looks_for_them() -> None:
    # Guards the test above against quietly asserting nothing if a file is
    # renamed: the paths the runtime resolves must be the paths built.
    for name in REQUIRED_DATA_FILES:
        assert (_SRC / name).is_file(), name
    assert set(REQUIRED_DATA_FILES) <= set(_data_files_in_source_tree())


def test_clean_wheel_installs_and_exposes_the_dex_lens_doorway(
    built_wheel: Path, tmp_path: Path
) -> None:
    """The shipped artifact imports, carries its data, and owns the CLI."""
    target = tmp_path / "installed"
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            str(target),
            str(built_wheel),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"wheel install failed:\n{completed.stderr}"

    script = """
from importlib.metadata import distributions
from pathlib import Path
import capability_exchange

target = Path(__import__('sys').argv[1]).resolve()
package = Path(capability_exchange.__file__).resolve().parent
assert package.is_relative_to(target), (package, target)
for relative in (
    'boundary/data_inventory.yaml',
    'adapters/claude_code/profiles/claude_code_containment.sb',
):
    assert (package / relative).is_file(), relative
distribution = next(distributions(path=[target]))
entry = next(
    item for item in distribution.entry_points
    if item.group == 'console_scripts' and item.name == 'dex-lens'
)
try:
    outcome = entry.load()(['--help'])
except SystemExit as exc:
    outcome = exc.code
assert outcome in (0, None), outcome
"""
    environment = environ.copy()
    environment["PYTHONPATH"] = str(target)
    environment["PYTHONNOUSERSITE"] = "1"
    invoked = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", script, str(target)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invoked.returncode == 0, invoked.stderr
    # The wheel's console script has to answer with the product, not with the
    # frozen browser journey's argparse help. Asserting on that help let the
    # packaging gate pass on a wheel whose real commands had all gone missing.
    for name in ("inventory", "catalogue", "brief", "reports", "share"):
        assert f"dex-lens {name}" in invoked.stdout, name
