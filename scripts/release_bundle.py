#!/usr/bin/env python3
"""Build and describe exact, signed Dex Lens public release artifacts.

The release workflow owns network access while collecting known wheels. The
installer receives only its signed archive and installs with pip offline. This
module keeps the exact release-manifest contract small enough to inspect and
strict enough to reject surprises before a user installs anything.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PRODUCT_NAME = "dex-lens"
SCHEMA_VERSION = 1
PYTHON_MINIMUM = "3.11"
PYTHON_MAXIMUM = "3.13"

SUPPORTED_TARGETS = frozenset(
    {
        "linux-x86_64",
        "linux-aarch64",
        "macos-arm64",
        "macos-x86_64",
    }
)

_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ASSET_FILENAME = re.compile(
    r"^dex-lens-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-"
    r"(linux-x86_64|linux-aarch64|macos-arm64|macos-x86_64)\.tar\.gz$"
)


class ReleaseValidationError(ValueError):
    """A release input or manifest was not safe to publish or install."""


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
