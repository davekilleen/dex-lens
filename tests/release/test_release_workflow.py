"""Static gates for the exact, manual-only public release workflow."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_release_workflow_is_manual_only_and_bound_to_one_exact_commit() -> None:
    workflow = _workflow()

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "schedule:" not in workflow
    assert "branches:" not in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "git rev-parse HEAD" in workflow
    assert '"$GITHUB_SHA"' in workflow
    assert 'test "$GITHUB_REF" = "refs/heads/main"' in workflow


def test_release_workflow_requires_the_dedicated_signing_secret() -> None:
    workflow = _workflow()

    assert "DEX_LENS_RELEASE_SIGNING_KEY_PEM" in workflow
    assert "Dedicated Dex Lens release signing key is not configured" in workflow
    assert "release-private.pem" in workflow
    assert "release-private.pem" not in "\n".join(
        line for line in workflow.splitlines() if "upload-artifact" in line or "path:" in line
    )
    assert "trap 'rm -f \"$PRIVATE_KEY\"' EXIT" in workflow
    unsigned_build = workflow.split("- name: Build the unsigned complete candidate", 1)[1].split(
        "- name: Require the dedicated release-signing key", 1
    )[0]
    assert "DEX_LENS_RELEASE_SIGNING_KEY_PEM" not in unsigned_build
    signing = workflow.split("- name: Sign the exact manifest", 1)[1].split(
        "- name: Render and syntax-check the public installer", 1
    )[0]
    assert "pip " not in signing
    assert "curl " not in signing


def test_release_workflow_proves_both_supported_consumer_paths_before_publish() -> None:
    workflow = _workflow()

    assert "ubuntu-latest" in workflow
    assert "macos-14" in workflow
    assert "scripts/smoke_release_installer.py" in workflow
    assert "DEX_LENS_INSTALL_ONLY" in workflow
    assert "needs: [build, smoke]" in workflow
    assert 'python: ["3.11", "3.14"]' in workflow


def test_release_workflow_publishes_one_complete_signed_asset_set() -> None:
    workflow = _workflow()

    for filename in (
        "release-manifest.json",
        "release-manifest.sig",
        "release-public-key.pem",
        "install.sh",
        "dex-lens-v${VERSION}-linux-x86_64.tar.gz",
        "dex-lens-v${VERSION}-macos-arm64.tar.gz",
    ):
        assert filename in workflow
    assert "gh release create" in workflow
    assert "--draft" in workflow
    assert "gh release edit" in workflow
    assert "--draft=false" in workflow


def test_release_workflow_never_installs_from_mutable_source_or_as_admin() -> None:
    workflow = _workflow().lower()

    assert "sudo" not in workflow
    assert "git clone" not in workflow
    assert "/archive/refs/heads/" not in workflow
    assert "raw.githubusercontent.com" not in workflow


def test_release_workflow_pins_actions_and_serializes_each_version() -> None:
    workflow = _workflow()
    action_uses = [
        line.strip()
        for line in workflow.splitlines()
        if re.match(r"-?\s*uses:", line.strip())
    ]

    assert action_uses
    assert all(re.search(r"@[0-9a-f]{40}(?:\s+#\s+v\d+\.\d+\.\d+)?$", line) for line in action_uses)
    assert "concurrency:" in workflow
    assert "group: dex-lens-release-${{ inputs.version }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "overwrite: true" in workflow
