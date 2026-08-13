"""Unit tests for the signed public-release manifest contract."""

from __future__ import annotations

import json

import pytest
from scripts.release_bundle import (
    ReleaseAsset,
    ReleaseManifest,
    ReleaseValidationError,
    parse_manifest_bytes,
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
        b'    "maximum": "3.13",\n'
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
    payload["assets"]["linux-aarch64"] = payload["assets"].pop("linux-x86_64")
    raw = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"

    with pytest.raises(ReleaseValidationError, match="filename"):
        parse_manifest_bytes(raw)
