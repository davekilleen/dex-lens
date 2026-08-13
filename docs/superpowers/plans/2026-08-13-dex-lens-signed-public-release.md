# Dex Lens signed public release — implementation plan

> **For Dave:** This is the machinery behind the one-line Mac/Linux command. It
> downloads one versioned Dex Lens bundle, checks that Dex signed it, installs
> it without administrator access, and opens the folder chooser. It never
> reads a Vault during installation.

**Goal:** Publish a versioned, signed Mac/Linux release that a person can start
with one pasted command, while preserving Dex Lens's local-first and
fail-closed trust boundaries.

**Architecture:** GitHub Releases holds four platform wheelhouse archives. A
release workflow builds the exact Lens wheel and the fixed runtime dependency
wheels for each supported OS/CPU target, signs an exact JSON manifest using a
dedicated P-256 signing key, and emits a version-specific `install.sh`. The
installer verifies the manifest signature with the embedded public key using
the system `openssl`, verifies the chosen archive SHA-256, installs only from
that archive into an isolated user-owned virtual environment, then starts
`dex-lens --choose-folder`. It does not use `sudo`, a mutable branch, PyPI, or
any Vault path.

**Scope:** Mac and Linux only: macOS Apple Silicon and Intel; Linux x86_64 and
ARM64; Python 3.11–3.13. Windows receives its separately bounded Preview after
this release path is proven.

**Important security choice:** The earlier public-launch design named Ed25519.
The installer runs before Python dependencies are installed, and OpenSSL 1.1.1
cannot verify Ed25519 through `pkeyutl`. P-256 + SHA-256 is supported by the
native `openssl dgst` command on the Mac/Linux baseline, so use a dedicated
P-256 release key solely for the bootstrap manifest. The existing Dex Core
catalogue remains Ed25519; never reuse its key for Lens releases.

**Do not do:** do not release from `main`, clone a branch in the installer,
install with `sudo`, let pip reach PyPI during install, inspect a chosen folder
before the in-product approval screen, or claim Windows support here.

---

## Release contract

The signed manifest is exact UTF-8 bytes and has this shape:

~~~json
{
  "schema_version": 1,
  "product": "dex-lens",
  "version": "0.1.0",
  "source_commit": "40-lowercase-hex",
  "python": {"minimum": "3.11", "maximum": "3.13"},
  "assets": {
    "linux-x86_64": {
      "filename": "dex-lens-v0.1.0-linux-x86_64.tar.gz",
      "sha256": "64-lowercase-hex"
    }
  }
}
~~~

The matching binary `release-manifest.sig` is a DER-encoded ECDSA P-256
signature over the exact manifest bytes. `install.sh` embeds the matching PEM
public key; it refuses unknown OS/CPU, missing tools, a bad signature, a bad
archive hash, an unsafe archive member, an unsupported Python version, or an
offline wheel install failure before launching Lens.

---

### Task 1: Add fixed release inputs and manifest primitives

**Files:**
- Create: `release/runtime-requirements.txt`
- Create: `scripts/release_bundle.py`
- Create: `tests/release/test_release_bundle.py`

- [ ] **Step 1: Write failing manifest tests**

Test that `ReleaseManifest`:

1. serializes deterministically;
2. rejects non-semver versions, bad commits, unsupported targets, duplicate
   targets, unsafe filenames and non-SHA-256 digests;
3. names only the requested platform archive; and
4. parses exact signed bytes without normalizing or accepting extra shape.

Use an in-memory `ReleaseManifest` fixture. Do not contact a registry or read a
real Vault.

- [ ] **Step 2: Run the focused tests and confirm red**

~~~sh
python -m pytest -q tests/release/test_release_bundle.py
~~~

Expected: FAIL because `scripts/release_bundle.py` does not yet exist.

- [ ] **Step 3: Add the exact runtime lock**

Create `release/runtime-requirements.txt` with the full direct and transitive
runtime set pinned to the versions proven available as wheels for the four
targets. It must contain one `distribution==version` per line, no ranges,
URLs, editable inputs or hashes that refer to a developer machine.

- [ ] **Step 4: Implement manifest types and validation**

In `scripts/release_bundle.py`:

- Define immutable `Target`, `ReleaseAsset`, and `ReleaseManifest` dataclasses.
- Support exactly `linux-x86_64`, `linux-aarch64`, `macos-arm64`, and
  `macos-x86_64`.
- Validate semantic version, a 40-character lowercase source commit, filename
  basename, and a 64-character lowercase SHA-256 before serialization.
- Encode manifest JSON with `sort_keys=True`, two-space indentation, a final
  newline, and UTF-8. Verification signs these exact bytes.

- [ ] **Step 5: Run focused checks and commit**

~~~sh
python -m pytest -q tests/release/test_release_bundle.py
ruff check scripts/release_bundle.py tests/release/test_release_bundle.py
git add release/runtime-requirements.txt scripts/release_bundle.py tests/release/test_release_bundle.py
git commit -m "Add signed release manifest contract"
~~~

### Task 2: Build platform wheelhouse archives without mutable dependencies

**Files:**
- Modify: `scripts/release_bundle.py`
- Modify: `tests/release/test_release_bundle.py`

- [ ] **Step 1: Write failing bundle tests**

Add tests that use temporary fake wheel files to prove the archive helper:

1. creates only regular files below one `wheelhouse/` root;
2. gives repeatable member ordering and zeroed timestamps;
3. rejects symlinks, paths outside its supplied directory and unexpected file
   types; and
4. records the archive SHA-256 in the manifest.

- [ ] **Step 2: Confirm the red state**

~~~sh
python -m pytest -q tests/release/test_release_bundle.py -k wheelhouse
~~~

Expected: FAIL until the builder exists.

- [ ] **Step 3: Implement the offline wheelhouse builder**

Add a `build` CLI to `scripts/release_bundle.py` which:

1. verifies its requested version equals `[project].version` in `pyproject.toml`;
2. builds the Lens wheel with fixed argv and no dependency resolution;
3. calls `python -m pip download --only-binary=:all: --no-deps` for every
   pinned runtime requirement, Python ABI (`cp311`, `cp312`, `cp313`) and
   declared OS/CPU tag;
4. combines the exact Lens wheel and only matching wheel files into one archive
   per target;
5. writes `release-manifest.json` only after every archive has a SHA-256; and
6. rejects a missing wheel, a source distribution, or a conflicting duplicate
   filename instead of falling back to PyPI at install time.

Use Python's tar/gzip APIs with fixed metadata, never a shell string. Archives
must be named `dex-lens-v<version>-<target>.tar.gz`.

- [ ] **Step 4: Run focused tests and build a local Linux proof bundle**

~~~sh
python -m pytest -q tests/release/test_release_bundle.py
python scripts/release_bundle.py build --version 0.1.0 --output /tmp/dex-lens-release-proof
~~~

Expected: the output contains exactly four archives, a manifest and no Vault
paths or user data.

- [ ] **Step 5: Commit the release builder**

~~~sh
git add scripts/release_bundle.py tests/release/test_release_bundle.py
git commit -m "Build offline Dex Lens release bundles"
~~~

### Task 3: Sign the manifest and render the hand-holding installer

**Files:**
- Modify: `scripts/release_bundle.py`
- Create: `scripts/render_release_installer.py`
- Create: `tests/release/test_release_installer.py`

- [ ] **Step 1: Write failing signature and installer tests**

Use a newly generated test-only P-256 key. Assert that:

1. an unmodified manifest signature verifies and any changed byte fails;
2. the renderer embeds only the PEM public key and never private key text;
3. the output calls `openssl dgst -sha256 -verify`, checks archive SHA-256,
   uses `--no-index` and `--only-binary=:all:` for pip, and contains no `sudo`,
   `git clone`, `pip install` from a URL or `curl |` inside itself;
4. Linux/Mac target detection selects the expected asset and unsupported
   Windows fails before downloading; and
5. the generated script names `dex-lens --choose-folder` and explains that no
   folder is read until the in-product approval screen.

- [ ] **Step 2: Confirm red**

~~~sh
python -m pytest -q tests/release/test_release_installer.py
~~~

Expected: FAIL before signer/renderer implementation.

- [ ] **Step 3: Implement exact signing**

Extend `scripts/release_bundle.py` with a `sign` CLI that accepts the manifest
path and a PEM P-256 private-key file, validates the key curve, writes a
DER-encoded `release-manifest.sig`, and emits the matching public PEM to a
specified path. The private key is read only from the supplied path and is
never printed, copied into an artifact or committed.

- [ ] **Step 4: Implement `install.sh` rendering**

`scripts/render_release_installer.py` takes version, release URL, manifest,
signature, and public PEM, then emits a version-specific POSIX `install.sh`.
The script must:

1. require `bash`, `curl`, `openssl`, and `python3` 3.11–3.13;
2. download the manifest and signature over HTTPS only;
3. verify signature first, parse target/asset fields with a short fixed Python
   block, download exactly that asset, and SHA-check it;
4. extract only regular `wheelhouse/` members with safe Python tar handling;
5. create `~/.local/share/dex-lens/versions/v<version>/venv`, install strictly
   offline, and create `~/.local/bin/dex-lens` without sudo;
6. start `dex-lens --choose-folder` by default; and
7. honour `DEX_LENS_INSTALL_ONLY=1` for release smoke tests while still
   performing every verification/install step.

- [ ] **Step 5: Run signature and renderer tests, then commit**

~~~sh
python -m pytest -q tests/release/test_release_bundle.py tests/release/test_release_installer.py
ruff check scripts/release_bundle.py scripts/render_release_installer.py tests/release
git add scripts/release_bundle.py scripts/render_release_installer.py tests/release
git commit -m "Add verified Dex Lens installer"
~~~

### Task 4: Make release publication repeatable and fail closed

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `README.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/superpowers/specs/2026-08-13-dex-lens-public-self-serve-launch-design.md`
- Modify: `tests/release/test_release_installer.py`

- [ ] **Step 1: Update the design constraint**

Record the P-256 bootstrap choice and dedicated signing-key boundary in the
public-launch design. Keep the guarantee: every public bundle is signed and
SHA-checked; do not claim a release exists yet.

- [ ] **Step 2: Add a manual, exact release workflow**

The workflow must only run by `workflow_dispatch`, take one semver `version`
input, check out the triggering immutable commit, run lint + release tests,
build all four bundles, require `DEX_LENS_RELEASE_SIGNING_KEY_PEM`, sign and
render, run `DEX_LENS_INSTALL_ONLY=1` smoke proof against the created assets,
then create a GitHub Release/tag at that exact commit. It must fail loudly when
the signing secret is absent; it must not create a partial release.

- [ ] **Step 3: Update the honest public documentation**

README must explain that public Mac/Linux release commands appear only after a
signed release is published; source build remains a technical route. STATUS
must say the release pipeline is built but unissued until the dedicated key is
configured and the real release workflow succeeds. Do not advertise an
unreleased command or Windows support.

- [ ] **Step 4: Test static release workflow constraints**

Add assertions that the workflow is manual-only, checks the signing secret,
publishes manifest/signature/installer plus all four expected archives, and
does not run a mutable branch installer or `sudo`.

- [ ] **Step 5: Run the full release slice**

~~~sh
python -m pytest -rs tests/release tests/test_packaging.py tests/concierge
ruff check scripts/release_bundle.py scripts/render_release_installer.py tests/release
python scripts/check_inventory.py
git diff --check origin/main...HEAD
~~~

Expected: all green. A real public release remains correctly blocked until the
dedicated signing key is supplied through GitHub's encrypted secret interface.

- [ ] **Step 6: Commit and prepare the pull request**

~~~sh
git add .github/workflows/release.yml README.md docs/STATUS.md docs/superpowers/specs/2026-08-13-dex-lens-public-self-serve-launch-design.md tests/release
git commit -m "Add signed public release workflow"
~~~

### Task 5: Release review and live proof

- [ ] Review the complete diff for vault access, data-inventory drift, mutable
  download sources and private-key leakage.
- [ ] Push the branch and open a pull request; wait for Linux and macOS CI.
- [ ] Merge only after the release-specific code and the existing trust gates
  are green.
- [ ] Configure the dedicated P-256 signing private key as
  `DEX_LENS_RELEASE_SIGNING_KEY_PEM` through GitHub's encrypted secret UI.
- [ ] Run the manual release workflow for the reviewed version, confirm the
  tag, four archives, manifest, signature and installer are present, then run
  the exact public one-line command in a clean Mac/Linux environment.
- [ ] Update Mission Control, Dispatch, README/STATUS and the live HeyDex
  distribution page together before telling anyone the command is public.
