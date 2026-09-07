"""The bundled fallback is an exact, re-verifiable signed catalogue snapshot.

The fallback used to be a second hand-maintained summary.  That made it
possible for the live catalogue and the packaged facts to disagree.  The
package now carries the signed source envelope itself plus only deterministic
provenance derived from that envelope.  The generator's self-check is the
drift gate; the packaging checks prove the exact checked bytes reach the wheel.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from capability_exchange.catalogue.v2 import (
    capability_class_of,
    default_keyring,
    verify_catalogue_envelope_for_stale_display,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_PACKAGE = "capability_exchange"
_REFERENCE_PATH = _SRC / _PACKAGE / "skill" / "dex-lens" / "dex-capabilities.json"
_WHEEL_RELATIVE_PATH = f"{_PACKAGE}/skill/dex-lens/dex-capabilities.json"

_ALLOWED_CLASSES = {"active-skill", "mcp-server", "scheduled-automation", "system-engine"}
_GENERATOR = _REPO_ROOT / "scripts" / "generate_capability_reference.py"

_BUILD_SCRIPT = """
import sys
from setuptools import build_meta

sys.stdout.write(build_meta.build_wheel(sys.argv[1]))
"""


@pytest.fixture(scope="module")
def reference() -> dict:
    with _REFERENCE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def verified(reference: dict):
    raw = json.dumps(reference["signed_catalogue"], sort_keys=True, separators=(",", ":"))
    return verify_catalogue_envelope_for_stale_display(raw, keyring=default_keyring())


def test_reference_file_exists() -> None:
    assert _REFERENCE_PATH.is_file()


def test_top_level_shape(reference: dict) -> None:
    assert set(reference) == {
        "note",
        "reference_version",
        "signed_catalogue",
        "source_catalogue",
    }
    assert reference["reference_version"] == 2
    assert set(reference["source_catalogue"]) == {
        "canonical_sha256",
        "catalog_version",
        "core_release",
        "key_id",
        "produced_at",
    }


def test_eight_declared_jobs(verified) -> None:
    # The JTBD taxonomy has exactly 8 jobs; a reference generated against a
    # different count (e.g. an old 5- or 11-job draft) is stale.
    assert len(verified.catalogue.jobs_taxonomy) == 8


def test_source_provenance_is_derived_from_the_verified_envelope(
    reference: dict, verified
) -> None:
    source = reference["source_catalogue"]
    assert source["catalog_version"] == verified.metadata.catalog_version
    assert source["core_release"] == verified.metadata.core_release
    assert source["key_id"] == verified.metadata.key_id
    assert source["produced_at"] == verified.metadata.produced_at.isoformat().replace(
        "+00:00", "Z"
    )


def test_all_four_capability_classes_are_represented(verified) -> None:
    present = {capability_class_of(entry) for entry in verified.catalogue.capabilities}
    assert present == _ALLOWED_CLASSES


def test_capability_counts_by_class(verified) -> None:
    from collections import Counter

    counts = Counter(capability_class_of(entry) for entry in verified.catalogue.capabilities)
    assert counts["active-skill"] >= 60, counts["active-skill"]
    assert counts["mcp-server"] >= 10, counts["mcp-server"]
    assert counts["scheduled-automation"] == 5, counts["scheduled-automation"]
    assert counts["system-engine"] >= 5, counts["system-engine"]


def test_committed_reference_is_exact_generated_output() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed local script and argv
        [sys.executable, str(_GENERATOR), "--check"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_generator_refuses_a_tampered_signed_source_without_writing(
    reference: dict, tmp_path: Path
) -> None:
    tampered = json.loads(json.dumps(reference["signed_catalogue"]))
    tampered["catalogue"]["capabilities"][0]["title"] += " tampered"
    source = tmp_path / "tampered-catalogue.json"
    output = tmp_path / "must-not-exist.json"
    source.write_text(json.dumps(tampered), encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - fixed local script and argv
        [
            sys.executable,
            str(_GENERATOR),
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "refused" in completed.stderr
    assert not output.exists()


# --- Packaging: the wheel must actually ship the reference. --------------
#
# Mirrors tests/test_packaging.py's approach: build a real wheel from a clean
# copy of the source tree via the PEP 517 hook directly (no network, no build
# isolation), then look inside the artifact rather than trusting the
# editable-install source tree.


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pytest.importorskip(
        "setuptools",
        reason=(
            "setuptools is the build backend and a declared dev dependency; "
            "without it the wheel-contents gate cannot run and the packaging "
            "of the capability reference is UNPROVEN here"
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
    with zipfile.ZipFile(built_wheel) as archive:
        return frozenset(archive.namelist())


def test_wheel_ships_the_capability_reference(wheel_contents: frozenset[str]) -> None:
    assert _WHEEL_RELATIVE_PATH in wheel_contents


def test_packaged_reference_matches_source_bytes(built_wheel: Path) -> None:
    # Guards against a stale copy shipping under the right name.
    with zipfile.ZipFile(built_wheel) as archive:
        packaged = archive.read(_WHEEL_RELATIVE_PATH)
    assert packaged == _REFERENCE_PATH.read_bytes()
