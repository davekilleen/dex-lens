"""Unit tests for the signed public-release manifest contract."""

from __future__ import annotations

import json
import re
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest
from scripts.release_bundle import (
    PYTHON_ABIS,
    ReleaseAsset,
    ReleaseManifest,
    ReleaseValidationError,
    _export_committed_project,
    build_wheelhouse_archive,
    parse_manifest_bytes,
    sha256_file,
)


def _asset(*, target: str = "linux-x86_64") -> ReleaseAsset:
    return ReleaseAsset(
        target=target,
        filename=f"dex-lens-v0.1.0-{target}.tar.gz",
        sha256="a" * 64,
    )


def _manifest(*, assets: tuple[ReleaseAsset, ...] = (_asset(),)) -> ReleaseManifest:
    return ReleaseManifest(
        version="0.1.0",
        source_commit="b" * 40,
        assets=assets,
    )


def test_manifest_serializes_to_stable_exact_bytes() -> None:
    manifest = _manifest()

    expected = (
        b'{\n'
        b'  "assets": {\n'
        b'    "linux-x86_64": {\n'
        b'      "filename": "dex-lens-v0.1.0-linux-x86_64.tar.gz",\n'
        b'      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
        b'    }\n'
        b'  },\n'
        b'  "product": "dex-lens",\n'
        b'  "python": {\n'
        b'    "maximum": "3.14",\n'
        b'    "minimum": "3.11"\n'
        b'  },\n'
        b'  "schema_version": 1,\n'
        b'  "source_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",\n'
        b'  "version": "0.1.0"\n'
        b'}\n'
    )

    assert manifest.to_bytes() == expected
    assert manifest.to_bytes() == manifest.to_bytes()
    assert parse_manifest_bytes(expected) == manifest
    assert PYTHON_ABIS == ("311", "312", "313", "314")


@pytest.mark.parametrize("version", ["v0.1.0", "1.2", "01.2.3", "1.02.3", "1.2.03"])
def test_manifest_rejects_non_semver_versions(version: str) -> None:
    with pytest.raises(ReleaseValidationError, match="semantic version"):
        ReleaseManifest(version=version, source_commit="b" * 40, assets=(_asset(),))


@pytest.mark.parametrize("commit", ["b" * 39, "B" * 40, "not-a-commit"])
def test_manifest_rejects_non_exact_source_commits(commit: str) -> None:
    with pytest.raises(ReleaseValidationError, match="source_commit"):
        ReleaseManifest(version="0.1.0", source_commit=commit, assets=(_asset(),))


@pytest.mark.parametrize(
    ("target", "filename", "digest", "message"),
    [
        ("windows-x86_64", "dex-lens-v0.1.0-windows-x86_64.tar.gz", "a" * 64, "target"),
        ("linux-x86_64", "../dex-lens-v0.1.0-linux-x86_64.tar.gz", "a" * 64, "filename"),
        ("linux-x86_64", "dex-lens-v0.1.0-linux-aarch64.tar.gz", "a" * 64, "filename"),
        ("linux-x86_64", "dex-lens-v0.1.0-linux-x86_64.tar.gz", "A" * 64, "sha256"),
        ("linux-x86_64", "dex-lens-v0.1.0-linux-x86_64.tar.gz", "a" * 63, "sha256"),
    ],
)
def test_asset_rejects_unsupported_or_unsafe_values(
    target: str, filename: str, digest: str, message: str
) -> None:
    with pytest.raises(ReleaseValidationError, match=message):
        ReleaseAsset(target=target, filename=filename, sha256=digest)


def test_manifest_rejects_duplicate_targets() -> None:
    with pytest.raises(ReleaseValidationError, match="duplicate"):
        _manifest(assets=(_asset(), _asset()))


def test_parse_rejects_extra_shape_instead_of_silently_normalizing() -> None:
    payload = json.loads(_manifest().to_bytes())
    payload["unexpected"] = "accepted nowhere"
    raw = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"

    with pytest.raises(ReleaseValidationError, match="unexpected"):
        parse_manifest_bytes(raw)


def test_parse_rejects_an_asset_with_a_mismatched_mapping_key() -> None:
    payload = json.loads(_manifest().to_bytes())
    payload["assets"]["macos-arm64"] = payload["assets"].pop("linux-x86_64")
    raw = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"

    with pytest.raises(ReleaseValidationError, match="filename"):
        parse_manifest_bytes(raw)


def _wheel(path: Path, contents: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def test_wheelhouse_archive_has_only_regular_wheels_with_fixed_metadata(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse-source"
    first = _wheel(wheelhouse / "pure-1.0.0-py3-none-any.whl", b"pure wheel")
    second = _wheel(wheelhouse / "nested" / "native-1.0.0-cp311.whl", b"native wheel")
    first_archive = tmp_path / "first.tar.gz"
    second_archive = tmp_path / "second.tar.gz"

    first_digest = build_wheelhouse_archive(wheelhouse, (first, second), first_archive)
    second_digest = build_wheelhouse_archive(wheelhouse, (second, first), second_archive)

    assert first_digest == sha256_file(first_archive)
    assert second_digest == sha256_file(second_archive)
    assert first_archive.read_bytes() == second_archive.read_bytes()
    with tarfile.open(first_archive) as archive:
        members = archive.getmembers()

    assert [member.name for member in members] == [
        "wheelhouse/native-1.0.0-cp311.whl",
        "wheelhouse/pure-1.0.0-py3-none-any.whl",
    ]
    assert all(member.isfile() for member in members)
    assert all(member.mtime == 0 for member in members)
    assert all(member.uid == 0 and member.gid == 0 for member in members)


def test_wheelhouse_archive_rejects_a_path_outside_its_declared_source(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse-source"
    inside = _wheel(wheelhouse / "inside-1.0.0.whl", b"inside")
    outside = _wheel(tmp_path / "outside-1.0.0.whl", b"outside")

    with pytest.raises(ReleaseValidationError, match="outside"):
        build_wheelhouse_archive(wheelhouse, (inside, outside), tmp_path / "release.tar.gz")


def test_wheelhouse_archive_rejects_symlinks_and_duplicate_filenames(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse-source"
    first = _wheel(wheelhouse / "first" / "same-1.0.0.whl", b"first")
    second = _wheel(wheelhouse / "second" / "same-1.0.0.whl", b"second")
    source = _wheel(tmp_path / "source-1.0.0.whl", b"source")
    symlink = wheelhouse / "linked-1.0.0.whl"
    symlink.parent.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(source)

    with pytest.raises(ReleaseValidationError, match="duplicate"):
        build_wheelhouse_archive(wheelhouse, (first, second), tmp_path / "duplicate.tar.gz")
    with pytest.raises(ReleaseValidationError, match="symlink"):
        build_wheelhouse_archive(wheelhouse, (symlink,), tmp_path / "symlink.tar.gz")


def test_release_source_export_uses_committed_bytes_not_the_working_tree(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release-test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repository, check=True)
    package = repository / "src" / "example"
    package.mkdir(parents=True)
    (repository / "README.md").write_text("committed readme\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
    module = package / "module.py"
    module.write_text("VALUE = 'committed'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    module.write_text("VALUE = 'working tree'\n", encoding="utf-8")
    (package / "untracked.py").write_text("UNTRACKED = True\n", encoding="utf-8")
    exported = tmp_path / "exported"

    _export_committed_project(repository, exported, commit)

    assert (exported / "src" / "example" / "module.py").read_text(encoding="utf-8") == (
        "VALUE = 'committed'\n"
    )
    assert not (exported / "src" / "example" / "untracked.py").exists()


def test_runtime_lock_pins_every_declared_application_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = {
        line.split("==", 1)[0].casefold().replace("_", "-")
        for line in (root / "release" / "runtime-requirements.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    declared = []
    for requirement in project["project"]["dependencies"]:
        name = re.split(r"[<>=!;[]", requirement, maxsplit=1)[0].strip().casefold()
        declared.append(name.replace("_", "-"))
    missing = [name for name in declared if name not in lock]
    assert missing == []
