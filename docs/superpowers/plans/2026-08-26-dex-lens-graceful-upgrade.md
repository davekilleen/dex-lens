# Dex Lens Graceful Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the signed installer recognise and safely upgrade an earlier official Dex Lens source installation while preserving its private copy and continuing to refuse unrelated commands.

**Architecture:** Classify the existing launcher before any download or write as absent, signed-release-owned, official-legacy-owned, or foreign. The generated Bash installer may repoint the first three states because deliberately running it is permission; it stops on the foreign state. A functional test runs the rendered installer against a sealed local release fixture so the exact legacy-to-signed symlink transition is proven without public network access.

**Tech Stack:** Python 3.11+, Bash, pytest, `tarfile`, existing release manifest/installer renderer, Ruff

---

## File structure

- Modify `tests/release/test_release_installer.py`: functional and dry-run regression coverage for launcher ownership, explanation, preservation, and refusal.
- Modify `scripts/render_release_installer.py`: early launcher classification, returning-user copy, safe repointing, and final rollback-location message.
- Modify `README.md`: explain that rerunning the signed installer refreshes Lens and its skill, while preserving an older official source install.

All commands below use the repository-local development environment. Create it
once if it is absent:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

### Task 1: Lock the legacy-upgrade experience with failing tests

**Files:**
- Modify: `tests/release/test_release_installer.py`

- [ ] **Step 1: Add a helper that creates the exact earlier official source installation**

Add this helper beside `_sealed_network`:

```python
def _legacy_source_launcher(home: Path) -> tuple[Path, Path]:
    legacy = home / ".local" / "share" / "dex-lens" / "venv" / "bin" / "dex-lens"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    legacy.chmod(0o755)
    launcher = home / ".local" / "bin" / "dex-lens"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(legacy)
    return launcher, legacy
```

- [ ] **Step 2: Add a dry-run regression test for returning users**

Use the rendered installer through `TestTheOptionsThePageDocuments._run`:

```python
def test_a_dry_run_recognises_an_earlier_official_lens_install(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    launcher, legacy = _legacy_source_launcher(home)

    completed, _, curl_called = TestTheOptionsThePageDocuments._run(
        tmp_path, home, "--dry-run", piped=True
    )

    assert completed.returncode == 0, completed.stderr
    assert "It looks like you used Dex Lens before" in completed.stdout
    assert "Because you ran this installer" in completed.stdout
    assert str(legacy.parent.parent.parent) in completed.stdout
    assert "left in place" in completed.stdout
    assert launcher.resolve() == legacy
    assert not curl_called.exists()
```

- [ ] **Step 3: Add a pre-network refusal test for an unrelated command**

```python
def test_a_foreign_launcher_is_refused_before_network_or_writes(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    foreign = tmp_path / "some-other-tool" / "dex-lens"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    foreign.chmod(0o755)
    launcher = home / ".local" / "bin" / "dex-lens"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(foreign)

    completed, _, curl_called = TestTheOptionsThePageDocuments._run(
        tmp_path, home, "--dry-run", piped=True
    )

    assert completed.returncode != 0
    assert str(launcher) in completed.stderr
    assert str(foreign) in completed.stderr
    assert "will not overwrite" in completed.stderr
    assert launcher.resolve() == foreign
    assert not curl_called.exists()
```

Add the regular-file counterpart so both foreign shapes from the design are
proven:

```python
def test_a_regular_launcher_is_refused_before_network_or_writes(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    launcher = home / ".local" / "bin" / "dex-lens"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    completed, _, curl_called = TestTheOptionsThePageDocuments._run(
        tmp_path, home, "--dry-run", piped=True
    )

    assert completed.returncode != 0
    assert str(launcher) in completed.stderr
    assert "will not overwrite" in completed.stderr
    assert launcher.is_file()
    assert not curl_called.exists()
```

- [ ] **Step 4: Prove a current signed launcher remains repeatable**

```python
def test_a_current_signed_launcher_remains_repeatable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    data_home = tmp_path / "signed-data"
    target = data_home / "dex-lens" / "versions" / "v0.0.9" / "venv" / "bin" / "dex-lens"
    target.parent.mkdir(parents=True)
    target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)
    launcher = home / ".local" / "bin" / "dex-lens"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(target)

    completed, _, curl_called = TestTheOptionsThePageDocuments._run(
        tmp_path,
        home,
        "--dry-run",
        piped=True,
        DEX_LENS_DATA_HOME=str(data_home),
    )

    assert completed.returncode == 0, completed.stderr
    assert launcher.resolve() == target
    assert not curl_called.exists()
```

- [ ] **Step 5: Add a sealed signed-release fixture for the real repointing proof**

Add `hashlib` and `tarfile` imports, then add this helper. It creates a valid
local archive and manifest, substitutes local `curl` and `openssl` commands,
and pre-creates the signed version's environment so no wheel is installed:

```python
def _run_sealed_signed_install(
    tmp_path: Path, home: Path
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    archive = tmp_path / "release.tar.gz"
    placeholder = tmp_path / "placeholder.whl"
    placeholder.write_bytes(b"not installed: signed version is pre-created")
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(placeholder, arcname="wheelhouse/placeholder.whl")
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()

    manifest = ReleaseManifest(
        version="0.1.0",
        source_commit="b" * 40,
        assets=(
            ReleaseAsset(
                target="linux-x86_64",
                filename="dex-lens-v0.1.0-linux-x86_64.tar.gz",
                sha256=archive_sha,
            ),
            ReleaseAsset(
                target="macos-arm64",
                filename="dex-lens-v0.1.0-macos-arm64.tar.gz",
                sha256=archive_sha,
            ),
        ),
    )
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_bytes(manifest.to_bytes())
    signature_path = tmp_path / "release-manifest.sig"
    signature_path.write_bytes(b"test signature; openssl is sealed below")

    _, public_key = _test_keypair(tmp_path)
    installer = tmp_path / "signed-install.sh"
    installer.write_text(
        render_installer(
            manifest=manifest,
            release_url=RELEASE_URL,
            public_key_pem=public_key.read_bytes(),
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "sealed-release-bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text(
        """#!/usr/bin/env bash
set -eu
output=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  */release-manifest.json) cp "$DEX_LENS_TEST_MANIFEST" "$output" ;;
  */release-manifest.sig) cp "$DEX_LENS_TEST_SIGNATURE" "$output" ;;
  */dex-lens-v0.1.0-*.tar.gz) cp "$DEX_LENS_TEST_ARCHIVE" "$output" ;;
  *) exit 91 ;;
esac
""",
        encoding="utf-8",
    )
    (fake_bin / "openssl").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    for command in (fake_bin / "curl", fake_bin / "openssl"):
        command.chmod(0o755)

    data_home = tmp_path / "signed-data"
    signed_target = (
        data_home
        / "dex-lens"
        / "versions"
        / "v0.1.0"
        / "venv"
        / "bin"
        / "dex-lens"
    )
    signed_target.parent.mkdir(parents=True)
    signed_target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    signed_target.chmod(0o755)
    (signed_target.parent / "python").symlink_to(sys.executable)

    skill_home = tmp_path / "skills"
    environment = os.environ | {
        "HOME": str(home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "DEX_LENS_DATA_HOME": str(data_home),
        "DEX_LENS_SKILLS_DIR": str(skill_home),
        "DEX_LENS_INSTALL_ONLY": "1",
        "DEX_LENS_NO_PING": "1",
        "DEX_LENS_TEST_MANIFEST": str(manifest_path),
        "DEX_LENS_TEST_SIGNATURE": str(signature_path),
        "DEX_LENS_TEST_ARCHIVE": str(archive),
    }
    completed = subprocess.run(
        ["bash", str(installer)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    return completed, signed_target, skill_home
```

- [ ] **Step 6: Add the functional migration test**

```python
def test_a_real_install_repoints_only_the_official_legacy_launcher(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    launcher, legacy = _legacy_source_launcher(home)

    completed, signed_target, skill_home = _run_sealed_signed_install(tmp_path, home)

    assert completed.returncode == 0, completed.stderr
    assert launcher.is_symlink()
    assert launcher.readlink() == signed_target
    assert legacy.exists(), "the rollback copy must remain untouched"
    assert (skill_home / "dex-lens" / "SKILL.md").is_file()
    assert (skill_home / "dex-lens" / "dex-capabilities.json").is_file()
    assert "It looks like you used Dex Lens before" in completed.stdout
    assert "Your earlier private copy is still" in completed.stdout
```

- [ ] **Step 7: Run the new tests and verify the expected failures**

Run:

```bash
.venv/bin/python -m pytest tests/release/test_release_installer.py \
  -k 'earlier_official or foreign_launcher or regular_launcher or current_signed or repoints_only' -q
```

Expected: the legacy-upgrade tests fail because the current renderer still
rejects the official legacy target and does not emit the returning-user
explanation. The current signed case passes; the foreign cases may fail on
their required pre-network wording until the early classifier exists.

- [ ] **Step 8: Commit the red tests**

```bash
git add tests/release/test_release_installer.py
git commit -m "test: reproduce upgrades from earlier Lens installs"
```

### Task 2: Implement safe launcher classification and migration

**Files:**
- Modify: `scripts/render_release_installer.py`
- Test: `tests/release/test_release_installer.py`

- [ ] **Step 1: Classify the launcher before the dry-run and download paths**

Immediately after `DEX_LENS_LAUNCHER` is defined, add generated Bash equivalent to:

```bash
DEX_LENS_LEGACY_SOURCE_ROOT="$HOME/.local/share/dex-lens"
DEX_LENS_LEGACY_SOURCE_TARGET="$DEX_LENS_LEGACY_SOURCE_ROOT/venv/bin/dex-lens"
DEX_LENS_LAUNCHER_STATE="absent"
DEX_LENS_EXISTING_TARGET=""

if [ -L "$DEX_LENS_LAUNCHER" ]; then
  DEX_LENS_EXISTING_TARGET="$(readlink "$DEX_LENS_LAUNCHER")"
  case "$DEX_LENS_EXISTING_TARGET" in
    "$DEX_LENS_DATA_HOME/dex-lens/versions/"*)
      DEX_LENS_LAUNCHER_STATE="signed"
      ;;
    "$DEX_LENS_LEGACY_SOURCE_TARGET")
      DEX_LENS_LAUNCHER_STATE="legacy-source"
      ;;
    *)
      die "Dex Lens found $DEX_LENS_LAUNCHER pointing to $DEX_LENS_EXISTING_TARGET. It cannot prove that command belongs to Lens, so it will not overwrite it. Nothing was downloaded or changed."
      ;;
  esac
elif [ -e "$DEX_LENS_LAUNCHER" ]; then
  die "Dex Lens found an existing command at $DEX_LENS_LAUNCHER. It cannot prove that command belongs to Lens, so it will not overwrite it. Nothing was downloaded or changed."
fi
```

This exact target check is the ownership proof. Do not accept relative links,
prefix matches, custom roots, or a command merely because running it produces
Lens-looking output.

- [ ] **Step 2: Explain the recognised legacy upgrade before the dry-run branch**

For `legacy-source`, print:

```text
It looks like you used Dex Lens before.
Because you ran this installer, Dex Lens will update its command and skill to the signed release.
Your earlier private copy at <legacy root> will be left in place, so the previous command can be restored if needed.
```

The wording must say what the installer will do, not that it has already done
it. It appears before both real and dry-run paths.

- [ ] **Step 3: Remove the late ownership refusal and retain only the repoint**

Replace the late `readlink`/`case` block with:

```bash
mkdir -p "$DEX_LENS_BIN_HOME"
ln -sfn "$DEX_LENS_VENV/bin/dex-lens" "$DEX_LENS_LAUNCHER"
```

The early classifier is now the single ownership gate. Keeping two gates would
allow their accepted-target rules and error copy to drift.

- [ ] **Step 4: Report the preserved rollback location after success**

After printing the installed command and skill locations, add:

```bash
if [ "$DEX_LENS_LAUNCHER_STATE" = "legacy-source" ]; then
  printf '%s\n' "Your earlier private copy is still in $DEX_LENS_LEGACY_SOURCE_ROOT for rollback."
fi
```

- [ ] **Step 5: Run the focused tests and verify green**

Run:

```bash
.venv/bin/python -m pytest tests/release/test_release_installer.py \
  -k 'earlier_official or foreign_launcher or regular_launcher or current_signed or repoints_only' -q
```

Expected: all selected tests pass. The functional case proves the launcher now
targets the signed version while the legacy executable and both skill files
remain present.

- [ ] **Step 6: Run all installer tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_install_script.py tests/release/test_release_installer.py tests/release/test_installer_parity.py tests/release/test_release_workflow.py -q
.venv/bin/python -m ruff check scripts/render_release_installer.py tests/release/test_release_installer.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 7: Commit the implementation**

```bash
git add scripts/render_release_installer.py tests/release/test_release_installer.py
git commit -m "fix: upgrade earlier official Lens installs safely"
```

### Task 3: Explain the lasting update model and verify the complete branch

**Files:**
- Modify: `README.md`
- Test: `tests/release/test_release_installer.py`

- [ ] **Step 1: Extend the installer-copy assertion**

Add assertions to `test_renderer_contains_only_the_public_key_and_offline_install_controls` that the rendered installer contains:

```python
assert "It looks like you used Dex Lens before" in installer
assert "Because you ran this installer" in installer
assert "will be left in place" in installer
assert "will not overwrite it" in installer
```

- [ ] **Step 2: Document the update model in plain language**

After the README's first-run paragraph, add:

```markdown
Run the same installer again when you want to update Lens. That deliberate run
updates both the command and the skill your assistant reads. If it recognises
an earlier official Lens installation, it explains the move and leaves the old
private copy in place for rollback. Lens does not silently update its software
in the background; its signed public Dex reference can refresh separately when
you ask Lens to make a comparison.
```

- [ ] **Step 3: Run the documentation and release tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_documentation.py tests/release -q
```

Expected: pass, with only documented environment-gated skips.

- [ ] **Step 4: Run the full local gate**

Run:

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check .
git diff --check
```

Expected: the full suite and Ruff pass; `git diff --check` prints nothing.

- [ ] **Step 5: Commit the public explanation**

```bash
git add README.md tests/release/test_release_installer.py
git commit -m "docs: explain deliberate Lens updates and rollback"
```

- [ ] **Step 6: Push and run the GitHub release gates**

After the repository GitHub preflight succeeds, push the branch and run the CI
workflow against the exact branch head using the current Core v1.97.1 catalogue
identity already pinned in `docs/pilot/live-catalogue-release.json`.

Expected: Linux and macOS test matrices, containment, egress, Section-6 live
bridge proof, and exact pilot-build release gate all pass. Keep PR #39 draft;
do not merge or publish a Lens release without separate founder approval.
