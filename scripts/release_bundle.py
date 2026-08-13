#!/usr/bin/env python3
"""Build and describe exact, signed Dex Lens public release artifacts.

The release workflow owns network access while collecting known wheels. The
installer receives only its signed archive and installs with pip offline. This
module keeps the exact release-manifest contract small enough to inspect and
strict enough to reject surprises before a user installs anything.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRODUCT_NAME = "dex-lens"
SCHEMA_VERSION = 1
PYTHON_MINIMUM = "3.11"
PYTHON_MAXIMUM = "3.13"
PYTHON_ABIS = ("311", "312", "313")
REPO_ROOT = Path(__file__).resolve().parents[1]

SUPPORTED_TARGETS = frozenset(
    {
        "linux-x86_64",
        "macos-arm64",
    }
)

_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ASSET_FILENAME = re.compile(
    r"^dex-lens-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-"
    r"(linux-x86_64|macos-arm64)\.tar\.gz$"
)
_PINNED_REQUIREMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9.!+_-]*$")


@dataclass(frozen=True)
class TargetSpec:
    """The pip compatibility selector for one supported public release target."""

    name: str
    pip_platform: str


TARGET_SPECS = {
    "linux-x86_64": TargetSpec("linux-x86_64", "manylinux_2_17_x86_64"),
    "macos-arm64": TargetSpec("macos-arm64", "macosx_11_0_arm64"),
}

_WHEEL_BUILD_SCRIPT = """
import sys
from setuptools import build_meta

sys.stdout.write(build_meta.build_wheel(sys.argv[1]))
"""


class ReleaseValidationError(ValueError):
    """A release input or manifest was not safe to publish or install."""


class ReleaseBuildError(ReleaseValidationError):
    """A release artifact could not be built exactly as requested."""


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unexpected or missing:
        detail: list[str] = []
        if unexpected:
            detail.append(f"unexpected={unexpected}")
        if missing:
            detail.append(f"missing={missing}")
        raise ReleaseValidationError(f"{label} keys are not exact: {', '.join(detail)}")


@dataclass(frozen=True)
class ReleaseAsset:
    """One signed, platform-specific offline wheelhouse archive."""

    target: str
    filename: str
    sha256: str

    def __post_init__(self) -> None:
        if self.target not in SUPPORTED_TARGETS:
            raise ReleaseValidationError(f"unsupported release target {self.target!r}")
        if not _ASSET_FILENAME.fullmatch(self.filename) or not self.filename.endswith(
            f"-{self.target}.tar.gz"
        ):
            raise ReleaseValidationError(
                "release asset filename must be a safe Dex Lens archive for its target"
            )
        if not _SHA256.fullmatch(self.sha256):
            raise ReleaseValidationError(
                "release asset sha256 must be 64 lowercase hexadecimal characters"
            )

    def to_dict(self) -> dict[str, str]:
        return {"filename": self.filename, "sha256": self.sha256}


@dataclass(frozen=True)
class ReleaseManifest:
    """The exact bytes a release signer approves before public publication."""

    version: str
    source_commit: str
    assets: tuple[ReleaseAsset, ...]

    def __post_init__(self) -> None:
        if not _SEMVER.fullmatch(self.version):
            raise ReleaseValidationError("release version must be a semantic version such as 0.1.0")
        if not _COMMIT.fullmatch(self.source_commit):
            raise ReleaseValidationError(
                "release source_commit must be a 40-character lowercase git commit"
            )
        if not self.assets:
            raise ReleaseValidationError("release manifest must name at least one platform archive")

        targets = [asset.target for asset in self.assets]
        if len(targets) != len(set(targets)):
            raise ReleaseValidationError("release manifest contains duplicate platform targets")
        for asset in self.assets:
            expected = f"dex-lens-v{self.version}-{asset.target}.tar.gz"
            if asset.filename != expected:
                raise ReleaseValidationError(
                    f"release asset filename {asset.filename!r} does not match {expected!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "product": PRODUCT_NAME,
            "version": self.version,
            "source_commit": self.source_commit,
            "python": {"minimum": PYTHON_MINIMUM, "maximum": PYTHON_MAXIMUM},
            "assets": {asset.target: asset.to_dict() for asset in self.assets},
        }

    def to_bytes(self) -> bytes:
        """Return the precise UTF-8 bytes covered by the release signature."""
        return (
            json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8")
            + b"\n"
        )


def parse_manifest_bytes(raw: bytes) -> ReleaseManifest:
    """Parse a received manifest without silently allowing unreviewed fields."""
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseValidationError("release manifest is not UTF-8") from exc
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ReleaseValidationError("release manifest is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ReleaseValidationError("release manifest must be a JSON object")

    _require_exact_keys(
        payload,
        frozenset({"schema_version", "product", "version", "source_commit", "python", "assets"}),
        "release manifest",
    )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ReleaseValidationError(
            f"unsupported release manifest schema {payload['schema_version']!r}"
        )
    if payload["product"] != PRODUCT_NAME:
        raise ReleaseValidationError(f"unexpected release product {payload['product']!r}")
    if not isinstance(payload["version"], str) or not isinstance(payload["source_commit"], str):
        raise ReleaseValidationError("release manifest version and source_commit must be strings")

    python = payload["python"]
    if not isinstance(python, dict):
        raise ReleaseValidationError("release manifest python range must be an object")
    _require_exact_keys(python, frozenset({"minimum", "maximum"}), "release manifest python")
    if python != {"minimum": PYTHON_MINIMUM, "maximum": PYTHON_MAXIMUM}:
        raise ReleaseValidationError("release manifest has an unsupported Python range")

    raw_assets = payload["assets"]
    if not isinstance(raw_assets, dict):
        raise ReleaseValidationError("release manifest assets must be an object")
    assets: list[ReleaseAsset] = []
    for target, raw_asset in raw_assets.items():
        if not isinstance(target, str) or not isinstance(raw_asset, dict):
            raise ReleaseValidationError("release manifest asset entries must be named objects")
        _require_exact_keys(raw_asset, frozenset({"filename", "sha256"}), f"release asset {target}")
        filename = raw_asset["filename"]
        sha256 = raw_asset["sha256"]
        if not isinstance(filename, str) or not isinstance(sha256, str):
            raise ReleaseValidationError(f"release asset {target} fields must be strings")
        assets.append(ReleaseAsset(target=target, filename=filename, sha256=sha256))

    return ReleaseManifest(
        version=payload["version"],
        source_commit=payload["source_commit"],
        assets=tuple(assets),
    )


def sha256_file(path: Path) -> str:
    """Return a file's SHA-256 without loading a release archive into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_wheel_within(source_root: Path, path: Path) -> Path:
    if path.is_symlink():
        raise ReleaseValidationError(f"wheelhouse input must not be a symlink: {path}")
    if not path.is_file():
        raise ReleaseValidationError(f"wheelhouse input must be a regular file: {path}")
    resolved_root = source_root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ReleaseValidationError(
            f"wheelhouse input is outside its source root: {path}"
        ) from exc
    if path.suffix != ".whl":
        raise ReleaseValidationError(f"wheelhouse input is not a wheel: {path.name}")
    return resolved_path


def build_wheelhouse_archive(
    source_root: Path,
    wheel_files: Iterable[Path],
    destination: Path,
) -> str:
    """Write a deterministic, safe wheelhouse archive and return its SHA-256.

    The release builder gives this function only wheels downloaded into a
    temporary target directory. Validation is repeated here so a future caller
    cannot accidentally archive a symlink, an arbitrary source file, or an
    unreviewed path outside that directory.
    """
    if not source_root.is_dir():
        raise ReleaseValidationError(f"wheelhouse source root is not a directory: {source_root}")
    if destination.exists():
        raise ReleaseValidationError(
            f"refusing to overwrite existing release archive: {destination}"
        )

    checked = [_require_wheel_within(source_root, Path(path)) for path in wheel_files]
    if not checked:
        raise ReleaseValidationError("wheelhouse archive requires at least one wheel")
    names = [path.name for path in checked]
    if len(names) != len(set(names)):
        raise ReleaseValidationError("wheelhouse archive contains duplicate wheel filenames")
    ordered = tuple(sorted(checked, key=lambda path: path.name))

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as raw_output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for wheel in ordered:
                    metadata = wheel.stat()
                    member = tarfile.TarInfo(name=f"wheelhouse/{wheel.name}")
                    member.size = metadata.st_size
                    member.mode = 0o644
                    member.mtime = 0
                    member.uid = 0
                    member.gid = 0
                    member.uname = ""
                    member.gname = ""
                    with wheel.open("rb") as wheel_bytes:
                        archive.addfile(member, wheel_bytes)
    return sha256_file(destination)


def _read_project_version(source_root: Path) -> str:
    pyproject = source_root / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            project = tomllib.load(handle)["project"]
        version = project["version"]
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseBuildError(f"could not read project version from {pyproject}") from exc
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ReleaseBuildError("project version must be a plain semantic version")
    return version


def _run_checked(
    arguments: list[str], *, cwd: Path, label: str
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(  # noqa: S603 - every caller supplies fixed argv
        arguments,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = " ".join((completed.stderr or completed.stdout).split())[:480]
        raise ReleaseBuildError(f"{label} failed: {detail or 'no diagnostic output'}")
    return completed


def _source_commit(source_root: Path) -> str:
    completed = _run_checked(
        ["git", "rev-parse", "HEAD"], cwd=source_root, label="read exact source commit"
    )
    commit = completed.stdout.strip()
    if not _COMMIT.fullmatch(commit):
        raise ReleaseBuildError("git did not return a 40-character source commit")
    return commit


def _runtime_requirements(path: Path) -> tuple[str, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ReleaseBuildError(f"runtime requirement lock is missing: {path}") from exc
    requirements = tuple(
        line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")
    )
    if not requirements:
        raise ReleaseBuildError("runtime requirement lock must not be empty")
    invalid = [
        requirement
        for requirement in requirements
        if not _PINNED_REQUIREMENT.fullmatch(requirement)
    ]
    if invalid:
        raise ReleaseBuildError(
            f"runtime requirement lock contains unsafe requirement(s): {invalid}"
        )
    normalized = [requirement.casefold() for requirement in requirements]
    if len(normalized) != len(set(normalized)):
        raise ReleaseBuildError("runtime requirement lock contains duplicate requirement(s)")
    return requirements


def _build_lens_wheel(source_root: Path, workspace: Path, python: str) -> Path:
    """Build from a source copy so ordinary release work never dirties the checkout."""
    project_copy = workspace / "project"
    project_copy.mkdir()
    shutil.copytree(source_root / "src", project_copy / "src")
    for filename in ("pyproject.toml", "README.md"):
        shutil.copy2(source_root / filename, project_copy / filename)
    wheel_output = project_copy / "dist"
    wheel_output.mkdir()
    completed = _run_checked(
        [python, "-c", _WHEEL_BUILD_SCRIPT, str(wheel_output)],
        cwd=project_copy,
        label="build Dex Lens wheel",
    )
    names = [
        line.strip() for line in completed.stdout.splitlines() if line.strip().endswith(".whl")
    ]
    if len(names) != 1:
        raise ReleaseBuildError("Dex Lens wheel build did not report exactly one wheel filename")
    wheel = wheel_output / names[0]
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ReleaseBuildError("Dex Lens wheel build did not produce its reported wheel")
    return wheel


def _download_target_wheels(
    *,
    python: str,
    requirements_path: Path,
    target: TargetSpec,
    destination: Path,
    source_root: Path,
) -> tuple[Path, ...]:
    destination.mkdir(parents=True, exist_ok=True)
    for abi_version in PYTHON_ABIS:
        _run_checked(
            [
                python,
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--only-binary=:all:",
                "--no-deps",
                "--dest",
                str(destination),
                "--platform",
                target.pip_platform,
                "--implementation",
                "cp",
                "--python-version",
                abi_version,
                "--abi",
                f"cp{abi_version}",
                "--requirement",
                str(requirements_path),
            ],
            cwd=source_root,
            label=f"download {target.name} CPython {abi_version} runtime wheels",
        )
    wheels = tuple(sorted(destination.glob("*.whl"), key=lambda path: path.name))
    if not wheels:
        raise ReleaseBuildError(f"no runtime wheels were downloaded for {target.name}")
    unexpected = sorted(path.name for path in destination.iterdir() if path.suffix != ".whl")
    if unexpected:
        raise ReleaseBuildError(
            f"runtime wheel download for {target.name} produced non-wheel files: {unexpected}"
        )
    return wheels


def _copy_wheel(source: Path, destination: Path) -> None:
    target = destination / source.name
    if target.exists():
        if sha256_file(target) != sha256_file(source):
            raise ReleaseBuildError(f"conflicting downloaded wheel filename: {source.name}")
        return
    shutil.copyfile(source, target)


def build_release_bundle(
    *,
    version: str,
    output: Path,
    source_root: Path = REPO_ROOT,
    python: str = sys.executable,
) -> ReleaseManifest:
    """Build all declared platform archives and their unsigned exact manifest."""
    if version != _read_project_version(source_root):
        raise ReleaseBuildError(
            f"requested release version {version!r} does not match pyproject version "
            f"{_read_project_version(source_root)!r}"
        )
    if output.exists() and any(output.iterdir()):
        raise ReleaseBuildError(f"release output directory must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    requirements_path = source_root / "release" / "runtime-requirements.txt"
    _runtime_requirements(requirements_path)
    source_commit = _source_commit(source_root)

    assets: list[ReleaseAsset] = []
    with tempfile.TemporaryDirectory(prefix="dex-lens-release-") as temporary:
        workspace = Path(temporary)
        lens_wheel = _build_lens_wheel(source_root, workspace, python)
        for target in TARGET_SPECS.values():
            downloaded = _download_target_wheels(
                python=python,
                requirements_path=requirements_path,
                target=target,
                destination=workspace / "downloaded" / target.name,
                source_root=source_root,
            )
            staging = workspace / "staging" / target.name
            staging.mkdir(parents=True)
            _copy_wheel(lens_wheel, staging)
            for wheel in downloaded:
                _copy_wheel(wheel, staging)
            filename = f"dex-lens-v{version}-{target.name}.tar.gz"
            archive = output / filename
            digest = build_wheelhouse_archive(staging, tuple(staging.glob("*.whl")), archive)
            assets.append(ReleaseAsset(target=target.name, filename=filename, sha256=digest))

    manifest = ReleaseManifest(version=version, source_commit=source_commit, assets=tuple(assets))
    (output / "release-manifest.json").write_bytes(manifest.to_bytes())
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build exact Dex Lens public release artifacts.")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build unsigned Mac/Linux wheelhouse archives.")
    build.add_argument(
        "--version", required=True, help="Must equal pyproject.toml's exact version."
    )
    build.add_argument(
        "--output", required=True, type=Path, help="New or empty release-output directory."
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            manifest = build_release_bundle(version=args.version, output=args.output)
            print(
                "built unsigned Dex Lens release "
                f"{manifest.version} for {len(manifest.assets)} targets"
            )
            return 0
    except ReleaseValidationError as exc:
        print(f"Dex Lens release build refused: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
