"""The bundled Dex capability reference — schema, coverage, and packaging.

``dex-capabilities.json`` is a release-bundled snapshot of Dex's full
capability surface across all four classes (active-skill, mcp-server,
scheduled-automation, system-engine) that Dex Lens ships alongside the live
signed catalogue, which lists skills only. These tests hold the reference to
its own declared shape and prove the wheel actually carries it — an
undeclared package-data entry builds cleanly and silently omits the file
(HANDOFF 5.5: prefer the check that cannot be forgotten).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_PACKAGE = "capability_exchange"
_REFERENCE_PATH = _SRC / _PACKAGE / "skill" / "dex-lens" / "dex-capabilities.json"
_WHEEL_RELATIVE_PATH = f"{_PACKAGE}/skill/dex-lens/dex-capabilities.json"

_ALLOWED_CLASSES = {"active-skill", "mcp-server", "scheduled-automation", "system-engine"}
_ALLOWED_TIERS = {"core", "high", "medium", "niche"}
_REQUIRED_FIELDS = {
    "id",
    "capability_class",
    "impact_tier",
    "title",
    "value",
    "jobs_served",
    "since_release",
}

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
def job_ids(reference: dict) -> set[str]:
    return {job["job_id"] for job in reference["jobs"]}


def test_reference_file_exists() -> None:
    assert _REFERENCE_PATH.is_file()


def test_top_level_shape(reference: dict) -> None:
    required = (
        "reference_version", "source_release", "generated_at", "note", "jobs", "capabilities"
    )
    for key in required:
        assert key in reference, key
    assert isinstance(reference["jobs"], list)
    assert isinstance(reference["capabilities"], list)


def test_eight_declared_jobs(job_ids: set[str]) -> None:
    # The JTBD taxonomy has exactly 8 jobs; a reference generated against a
    # different count (e.g. an old 5- or 11-job draft) is stale.
    assert len(job_ids) == 8


def test_job_entries_are_well_formed(reference: dict) -> None:
    for job in reference["jobs"]:
        assert set(job.keys()) == {"job_id", "title"}
        assert job["job_id"]
        assert job["title"]


def test_every_capability_has_required_fields(reference: dict) -> None:
    missing = [
        entry.get("id", "<no id>")
        for entry in reference["capabilities"]
        if not _REQUIRED_FIELDS <= entry.keys()
    ]
    assert not missing, f"capabilities missing required fields: {missing}"


def test_capability_class_is_from_the_allowed_enum(reference: dict) -> None:
    bad = [
        entry["id"]
        for entry in reference["capabilities"]
        if entry["capability_class"] not in _ALLOWED_CLASSES
    ]
    assert not bad, f"capabilities with an unrecognized capability_class: {bad}"


def test_impact_tier_is_from_the_allowed_enum(reference: dict) -> None:
    bad = [
        entry["id"]
        for entry in reference["capabilities"]
        if entry["impact_tier"] not in _ALLOWED_TIERS
    ]
    assert not bad, f"capabilities with an unrecognized impact_tier: {bad}"


def test_every_jobs_served_id_is_a_declared_job(reference: dict, job_ids: set[str]) -> None:
    bad = [
        (entry["id"], served)
        for entry in reference["capabilities"]
        for served in entry["jobs_served"]
        if served not in job_ids
    ]
    assert not bad, f"capabilities referencing an undeclared job id: {bad}"


def test_every_capability_has_at_least_one_job_served(reference: dict) -> None:
    empty = [entry["id"] for entry in reference["capabilities"] if not entry["jobs_served"]]
    assert not empty, f"capabilities with no jobs_served: {empty}"


def test_capability_ids_are_unique(reference: dict) -> None:
    ids = [entry["id"] for entry in reference["capabilities"]]
    assert len(ids) == len(set(ids))


def test_mcp_servers_declare_tool_count(reference: dict) -> None:
    for entry in reference["capabilities"]:
        if entry["capability_class"] == "mcp-server":
            assert isinstance(entry.get("tool_count"), int) and entry["tool_count"] > 0, entry["id"]


def test_scheduled_automations_declare_cadence(reference: dict) -> None:
    for entry in reference["capabilities"]:
        if entry["capability_class"] == "scheduled-automation":
            assert entry.get("cadence"), entry["id"]


def test_all_four_capability_classes_are_represented(reference: dict) -> None:
    # The point of this reference: proving Dex Lens's comparison surface is
    # not skills-only, unlike the live signed catalogue.
    present = {entry["capability_class"] for entry in reference["capabilities"]}
    assert present == _ALLOWED_CLASSES


def test_capability_counts_by_class(reference: dict) -> None:
    from collections import Counter

    counts = Counter(entry["capability_class"] for entry in reference["capabilities"])
    assert counts["active-skill"] >= 60, counts["active-skill"]
    assert counts["mcp-server"] == 10, counts["mcp-server"]
    assert counts["scheduled-automation"] == 5, counts["scheduled-automation"]
    assert counts["system-engine"] >= 5, counts["system-engine"]


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
