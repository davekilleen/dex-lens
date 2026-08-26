# Dex Lens harness-neutral installer hand-off implementation plan

> **For the implementation session:** execute this plan task by task with
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** End the one-paste Dex Lens installer inside the person's chosen,
supported AI coding assistant, without printing a second command containing a
temporary PATH assignment.

**Architecture:** Add one standard-library-only Python module to the signed
`capability_exchange` package. It owns the supported-harness registry, safe
selection, shared preference, real-Terminal chooser, launch, and fallback
wording. Both Bash installers call that installed module after installation.
Bash continues to own source or signed-artifact installation; Python owns only
the post-install hand-off.

**Tech stack:** Python 3.11, Bash, pytest, POSIX pseudo-terminals, Ruff,
setuptools packaging, and the existing release-installer renderer.

**Delivery boundary:** Produce a tested draft PR only. Do not bump the version,
merge, tag, sign, publish a release, change `heydex.ai/lens`, or deploy website
copy. Each of those actions belongs to a later release task with explicit
approval.

---

## Task 1: Build the verified harness registry and safe preference

**Files:**

- Create: `src/capability_exchange/installer_handoff.py`
- Create: `tests/release/test_installer_handoff.py`

### Step 1: Write failing registry and selection tests

Create `tests/release/test_installer_handoff.py`. Import these public objects:

```python
from capability_exchange.installer_handoff import (
    HarnessAdapter,
    PreferenceError,
    SelectionError,
    available_harnesses,
    load_preference,
    preference_path,
    save_preference,
    select_without_prompt,
)
```

Add tests proving:

1. `HarnessAdapter.registry(home)` contains exactly `claude` then `codex`.
2. Claude Code declares command `claude`, display name `Claude Code`, and the
   `.claude/skills` plus `.agents/skills` homes beneath the supplied home.
3. Codex declares command `codex`, display name `Codex`, and the
   `.codex/skills` plus `.agents/skills` homes.
4. `available_harnesses` includes only commands returned by an injected
   `which` function and preserves registry order.
5. One available adapter is selected automatically.
6. A valid saved adapter wins when both are available.
7. A registered explicit adapter wins over a saved adapter.
8. An unknown explicit value raises `SelectionError` and names the accepted
   identifiers.
9. A registered but unavailable explicit value raises `SelectionError` and
   names the missing program.
10. Several adapters without a valid preference return no selection, meaning
    the interactive chooser is required.
11. No adapters return no selection, meaning the plain-language fallback is
    required.

Use an injected lookup in tests:

```python
def fake_which(commands: set[str]):
    def lookup(command: str) -> str | None:
        return f"/fake/bin/{command}" if command in commands else None

    return lookup
```

### Step 2: Run the focused test and confirm the missing module failure

```bash
.venv/bin/python -m pytest tests/release/test_installer_handoff.py -q
```

Expected: collection fails because `capability_exchange.installer_handoff`
does not exist.

### Step 3: Implement the fixed registry and pure selection

In `src/capability_exchange/installer_handoff.py`, define:

```python
FIRST_QUESTION = (
    "Use Dex Lens to have a look at my setup and tell me what Dex has that I don't."
)


class SelectionError(ValueError):
    """An explicit harness request cannot be honoured safely."""


@dataclass(frozen=True)
class HarnessAdapter:
    identifier: str
    display_name: str
    command: str
    skill_homes: Sequence[Path]
```

`HarnessAdapter.registry(home)` must construct the two adapters directly. It
must not load plugins, inspect histories, evaluate environment text, or infer an
adapter from an executable name. `available_harnesses` receives `which` as an
argument. The CLI will supply `shutil.which`; unit tests supply the fake.

Implement `select_without_prompt(available, explicit, saved)` in this order:

1. Validate `explicit` against the fixed registry and current availability.
2. Return the explicit adapter when valid.
3. Return `saved` only if that adapter is currently available.
4. Return the only available adapter when the count is one.
5. Return `None` for a genuine tie or no available adapter.

### Step 4: Write failing shared-preference tests

Add tests proving:

- `preference_path(home, xdg_state_home)` returns
  `<xdg-state>/dex-lens/harness-preference` when XDG state is supplied;
- it falls back to
  `<home>/.local/state/dex-lens/harness-preference` otherwise;
- `save_preference(path, "codex")` round-trips through `load_preference`;
- the saved file mode is `0600`;
- the containing directory is private when first created;
- unknown file contents, a directory, an unreadable file, and a symbolic link
  all load as no valid preference;
- saving an unknown identifier raises `PreferenceError`;
- saving through an existing symbolic link raises `PreferenceError` without
  changing its target; and
- monkeypatched `os.replace` observes source and destination in the same
  directory, while a simulated replace failure leaves the previous preference
  intact and no temporary file behind.

### Step 5: Run the tests and observe the missing preference API

```bash
.venv/bin/python -m pytest tests/release/test_installer_handoff.py -q
```

Expected: registry tests pass; preference tests fail because the preference API
has not been implemented.

### Step 6: Implement the shared preference atomically

Add `PreferenceError`, `preference_path`, `load_preference`, and
`save_preference`.

The writer must:

1. reject identifiers outside `HarnessAdapter.registry()`;
2. refuse an existing symbolic link before creating a temporary file;
3. create the parent with mode `0700` when absent;
4. create a temporary file in that same parent with `tempfile.mkstemp`;
5. write one identifier plus a newline, flush, and `os.fsync`;
6. set the file to `0600`;
7. check the destination for a symbolic link again;
8. atomically replace with `os.replace`; and
9. remove the temporary file on every failure path.

Do not delete a stale value merely by reading it. Replace a stale value only
after a person makes a new choice. This prevents dry-run and no-launch modes
from producing hidden writes.

### Step 7: Verify and commit Task 1

```bash
.venv/bin/python -m pytest tests/release/test_installer_handoff.py -q
.venv/bin/python -m ruff check \
  src/capability_exchange/installer_handoff.py \
  tests/release/test_installer_handoff.py
git add src/capability_exchange/installer_handoff.py \
  tests/release/test_installer_handoff.py
git commit -m "feat: define safe Lens harness selection"
```

Expected: tests and Ruff pass, then the first implementation commit is created.

---

## Task 2: Add the real-Terminal chooser and launch boundary

**Files:**

- Modify: `src/capability_exchange/installer_handoff.py`
- Modify: `tests/release/test_installer_handoff.py`
- Create if reuse requires it: `tests/release/pty_support.py`

### Step 1: Build a pseudo-Terminal regression helper

The critical journey must model the documented install shape accurately:
installer source arrives on stdin through a pipe, while the process still owns
a controlling Terminal at `/dev/tty`.

In `tests/release/pty_support.py`, implement
`run_with_script_pipe_and_controlling_tty(argv, script, keyboard, env, timeout)`
with this sequence:

1. create a pipe for the script;
2. call `pty.fork()` to give the child a controlling pseudo-Terminal;
3. in the child, replace file descriptor 0 with the script pipe and call
   `os.execvpe` with the supplied argument list;
4. in the parent, write the script to the pipe and close it;
5. exchange chooser and harness keyboard bytes through the PTY master;
6. collect Terminal output with `select.select` until the child exits;
7. translate wait status with `os.waitstatus_to_exitcode`;
8. tolerate the normal end-of-PTY `EIO` on Linux;
9. kill and reap the child if the deadline expires; and
10. close every descriptor in `finally`.

Return a frozen result containing `returncode` and decoded `output`. The helper
must never call a real Claude Code or Codex executable.

### Step 2: Write failing chooser and launch journeys

Create fake `claude` and `codex` executables under a temporary `bin` directory.
Each fake must record its argument list, print `HARNESS_READY`, read one keyboard
line, record that line, and exit.

Add tests proving:

- Claude Code alone launches Claude Code with `FIRST_QUESTION`;
- Codex alone launches Codex with the identical question;
- both installed show `1. Claude Code` and `2. Codex` through `/dev/tty`;
- choosing `2` saves Codex and a second run opens Codex without asking;
- invalid input explains the valid choices, then accepts a valid input;
- text typed after `HARNESS_READY` reaches the fake harness;
- `DEX_LENS_HARNESS=codex` bypasses a two-adapter chooser;
- an unknown or unavailable explicit adapter exits non-zero safely;
- missing `/dev/tty` or chooser EOF prints the plain-language fallback and
  exits zero without hanging;
- `DEX_LENS_INSTALL_ONLY=1` and `DEX_LENS_NO_LAUNCH=1` do not discover, prompt,
  save, or launch;
- dry-run discovers and describes but never opens `/dev/tty`, saves, or
  launches;
- verbose output names the selected adapter and preference path; and
- normal output contains no preference path, install path, or PATH assignment.

### Step 3: Run the new journeys and confirm the missing hand-off failure

```bash
.venv/bin/python -m pytest tests/release/test_installer_handoff.py -q
```

Expected: preference and pure-selection tests pass; CLI journeys fail.

### Step 4: Implement the hand-off CLI

Add this options object:

```python
@dataclass(frozen=True)
class HandoffOptions:
    install_only: bool
    no_launch: bool
    dry_run: bool
    verbose: bool
    explicit_harness: str | None
    bin_home: Path
    home: Path
    xdg_state_home: Path | None
```

Implement these functions with the named responsibilities:

- `choose_from_terminal(available, terminal_path)`: open `/dev/tty` separately
  for reading and writing; print the numbered display names; retry invalid
  input; return `None` on EOF or device failure; never read from stdin.
- `launch_harness(adapter, bin_home, terminal_path)`: open `/dev/tty`, duplicate
  it onto stdin/stdout/stderr, prepend `bin_home` to a copied PATH, and call
  `os.execvpe(adapter.command, [adapter.command, FIRST_QUESTION], environment)`.
  Never use `eval`, `shell=True`, or a command string.
- `print_fallback(display_name=None)`: say Lens is ready, optionally say the
  named assistant could not be opened, and print `FIRST_QUESTION` as prose.
- `run_handoff(options)`: enforce the two absolute gates before discovery;
  perform side-effect-free dry-run reporting; load the shared preference;
  apply deterministic selection; ask only for an unresolved multi-adapter tie;
  save only a chooser result; print concise/verbose output; then launch.
- `main(argv=None)`: parse flags, build `HandoffOptions`, convert safe selection
  errors into clear exit code 2 messages, and return the hand-off result.

End the module with:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

Use these approved normal endings:

```text
Dex Lens is ready.
Opening Codex…
```

```text
Dex Lens is ready.
Open your usual AI coding assistant and ask:

  Use Dex Lens to have a look at my setup and tell me what Dex has that I don't.
```

A launch failure must not undo or describe the completed install as failed.
Print the fallback and return zero because installation succeeded.

### Step 5: Verify and commit Task 2

```bash
.venv/bin/python -m pytest tests/release/test_installer_handoff.py -q
.venv/bin/python -m ruff check \
  src/capability_exchange/installer_handoff.py \
  tests/release/test_installer_handoff.py \
  tests/release/pty_support.py
git add src/capability_exchange/installer_handoff.py \
  tests/release/test_installer_handoff.py \
  tests/release/pty_support.py
git commit -m "feat: hand Lens off through the real terminal"
```

If the helper stays in the main test module, omit the nonexistent helper path
from Ruff and `git add`. Expected: all hand-off journeys pass on POSIX.

---

## Task 3: Integrate the generated signed installer

**Files:**

- Modify: `scripts/render_release_installer.py`
- Modify: `tests/release/test_release_installer.py`
- Modify: `scripts/smoke_release_installer.py`

### Step 1: Replace the old signed-installer expectations

Remove `_hand_off_line`, `_start_line`, and tests that require `One more paste`
or a printed PATH assignment from `tests/release/test_release_installer.py`.

Add failing tests that assert the rendered installer:

```python
assert '"$DEX_LENS_VENV/bin/python" -m capability_exchange.installer_handoff' in installer
assert "DEX_LENS_HARNESS" in installer
assert "DEX_LENS_VERBOSE" in installer
assert 'exec "$DEX_LENS_ASSISTANT"' not in installer
assert "One more paste" not in installer
```

Extend the sealed signed-install helper to accept fake harness commands,
hand-off environment controls, isolated XDG state, and the PTY runner. Add
journeys for one adapter, two-adapter choice and reuse, explicit override,
missing Terminal, install-only, no-launch, concise output, and verbose output.
Prove the module runs from `DEX_LENS_VENV`, which contains the verified wheel,
not from the checkout.

### Step 2: Run and observe failures against the old renderer

```bash
.venv/bin/python -m pytest tests/release/test_release_installer.py -q
```

Expected: the new assertions fail because the renderer still contains
Claude-first Bash selection and the second-paste ending.

### Step 3: Validate controls before any download or write

Near existing option parsing in the rendered shell template, accept only:

```text
DEX_LENS_INSTALL_ONLY: 0 or 1
DEX_LENS_NO_LAUNCH: 0 or 1
DEX_LENS_VERBOSE: 0 or 1
DEX_LENS_HARNESS: empty, claude, or codex
```

Reject anything else with `die`. Escape braces correctly inside the Python
format template. Add tests proving invalid values fail before the sealed
network records a request.

### Step 4: Remove duplicated routing and call the installed module

Delete `DEX_LENS_ASSISTANT` discovery and both old final branches. After signed
install verification, skill placement, optional anonymous ping, and temporary
download cleanup, build a quoted Bash array with:

```text
--bin-home "$DEX_LENS_BIN_HOME"
--home "$HOME"
--xdg-state-home "$XDG_STATE_HOME" when nonempty
--install-only when requested
--no-launch when requested
--verbose when requested
--harness "$DEX_LENS_HARNESS" when nonempty
```

Finish with:

```bash
exec "$DEX_LENS_VENV/bin/python" -m capability_exchange.installer_handoff \
  "${DEX_LENS_HANDOFF_ARGS[@]}"
```

For `--dry-run`, keep a small Bash description when the installed environment
does not yet exist. It may read current command availability and the preference
file, but it must not download, write, prompt, or launch.

### Step 5: Make normal output concise without hiding consent facts

Normal output must retain:

- Lens has read nothing and never changes what it inspects;
- the anonymous one-time install note, when one was sent; and
- the fact that a recognised legacy copy remains available for recovery.

Hide install root, launcher, skill homes, preference path, ping-state path, and
legacy rollback path unless `DEX_LENS_VERBOSE=1` or `--dry-run` is active. Keep
the existing separate PATH discoverability warning for future shell sessions;
this work removes only the bottom second-paste hand-off.

### Step 6: Strengthen the signed release smoke proof

Retain `DEX_LENS_INSTALL_ONLY=1` in `scripts/smoke_release_installer.py`. Assert
that its output contains the install-only completion sentinel and contains none
of `Which assistant`, `Opening Claude`, `Opening Codex`, or `One more paste`.
Continue proving the command and the complete skill directory came from the
signed wheel.

### Step 7: Verify and commit Task 3

```bash
.venv/bin/python -m pytest \
  tests/release/test_installer_handoff.py \
  tests/release/test_release_installer.py -q
.venv/bin/python scripts/smoke_release_installer.py --help
.venv/bin/python -m ruff check \
  scripts/render_release_installer.py \
  scripts/smoke_release_installer.py \
  tests/release/test_release_installer.py
git add scripts/render_release_installer.py \
  scripts/smoke_release_installer.py \
  tests/release/test_release_installer.py
git commit -m "feat: route the signed installer to the chosen harness"
```

Use the existing release-test fixture to render the same installer twice and
compare SHA-256 values. Expected: focused tests pass, smoke help answers, Ruff
is clean, and rendering is byte-for-byte reproducible.

---

## Task 4: Integrate the source installer and restore parity

**Files:**

- Modify: `install.sh`
- Modify: `tests/test_install_script.py`
- Modify: `tests/release/test_installer_parity.py`

### Step 1: Replace old source-installer expectations

Remove `hand_off_line`, `printed_start_line`, and tests requiring the old second
paste. Add failing source journeys matching the signed-installer cases:

- Claude-only and Codex-only auto-open;
- two-adapter chooser and remembered result;
- explicit registered override;
- no adapter and no Terminal fallbacks;
- install-only and no-launch absolute gates;
- concise normal and complete verbose output; and
- spaces in HOME, `DEX_LENS_HOME`, and `DEX_LENS_BIN` remain quoted correctly.

Reuse `tests/release/pty_support.py`; do not copy its PTY logic.

### Step 2: Add observable parity coverage

Parameterise both installer forms in
`tests/release/test_installer_parity.py` over:

| Available | Saved | Explicit | Gate | Expected ending |
| --- | --- | --- | --- | --- |
| Codex | none | none | none | opens Codex |
| Claude Code | none | none | none | opens Claude Code |
| both | none | none | none | asks once |
| both | Codex | none | none | opens Codex without asking |
| both | Codex | Claude Code | none | opens Claude Code |
| none | none | none | none | prose fallback |
| both | none | none | no-launch | no prompt or launch |
| both | none | none | install-only | no prompt or launch |

Compare return code, prompt presence, selected fake harness, preference write,
and closing copy. Do not compare internal Bash variable names.

### Step 3: Run and confirm failures against `install.sh`

```bash
.venv/bin/python -m pytest \
  tests/test_install_script.py \
  tests/release/test_installer_parity.py -q
```

Expected: failures show source-only Claude-first routing and the printed
second-paste behavior.

### Step 4: Validate the same controls and invoke the module

Document and validate the four controls from Task 3 before cloning or writing.
Delete `ASSISTANT` discovery and both old ending branches. After venv install,
skill placement, executable proof, optional ping, and concise/verbose summary,
build the same quoted argument list and finish with:

```bash
exec "$VENV_DIR/bin/python" -m capability_exchange.installer_handoff \
  "${HANDOFF_ARGS[@]}"
```

Keep source dry-run side-effect-free and behaviorally equivalent to signed
dry-run. Preserve all existing source, bin, skill, ping, and safety overrides.

### Step 5: Verify and commit Task 4

```bash
.venv/bin/python -m pytest \
  tests/release/test_installer_handoff.py \
  tests/test_install_script.py \
  tests/release/test_release_installer.py \
  tests/release/test_installer_parity.py -q
bash -n install.sh
.venv/bin/python -m ruff check \
  src/capability_exchange/installer_handoff.py \
  tests/release/test_installer_handoff.py \
  tests/release/pty_support.py \
  tests/test_install_script.py \
  tests/release/test_release_installer.py \
  tests/release/test_installer_parity.py
git add install.sh tests/test_install_script.py \
  tests/release/test_installer_parity.py
git commit -m "feat: make the Lens source installer harness-neutral"
```

Expected: source, signed, and parity tests pass; Bash syntax and Ruff are clean.

---

## Task 5: Record unreleased truth, run all gates, and update draft PR #40

**Files:**

- Modify: `docs/STATUS.md`
- Review only: `README.md`
- Review only: `CHANGELOG.md`
- Review only: every file changed from the upstream merge base

### Step 1: Write the unreleased status before claiming completion

Add a `docs/STATUS.md` entry stating that the draft branch implements:

- verified Claude Code and Codex adapters;
- automatic routing for one adapter and a remembered choice for two;
- shared private state beneath the user's XDG state directory;
- real-Terminal reconnection for a piped installer; and
- absolute install-only and no-launch controls.

State plainly that v0.1.10, the live installer, release assets, and website copy
are unchanged. The release gate is a separate approval plus signed Linux and
macOS installer proofs. Do not edit README or CHANGELOG as if this were public.

### Step 2: Run focused regression and package proofs

```bash
.venv/bin/python -m pytest \
  tests/release/test_installer_handoff.py \
  tests/test_install_script.py \
  tests/release/test_release_installer.py \
  tests/release/test_installer_parity.py \
  tests/test_packaging.py -q
```

Expected: all focused tests pass. Packaging proves the new Python module ships
inside the wheel without adding package-data configuration.

### Step 3: Run the complete repository gates

```bash
.venv/bin/python -m pytest tests
.venv/bin/python -m ruff check .
bash -n install.sh
```

Expected: full tests pass with only documented environment-gated skips, Ruff is
clean, and Bash parses successfully.

### Step 4: Repeat two outcome-level PTY journeys manually

Use disposable homes and fake harnesses only:

1. Run each installer form from a script pipe with Codex alone. Confirm
   `Opening Codex…`, type a sentinel after `HARNESS_READY`, and prove the fake
   Codex process receives it.
2. Run with both adapters, choose Codex, then rerun. Confirm the second run opens
   Codex without asking.

Capture command, exit code, and concise transcript in the PR verification
comment. Never point these checks at a real home or real assistant executable.

### Step 5: Review the complete diff and release truth

```bash
BASE="$(git merge-base upstream/main HEAD)"
git diff --check "$BASE" HEAD
git diff --stat "$BASE" HEAD
git diff "$BASE" HEAD -- \
  src/capability_exchange/installer_handoff.py \
  install.sh \
  scripts/render_release_installer.py \
  scripts/smoke_release_installer.py \
  tests docs/STATUS.md
rg -n "v0\.1\.10|One more paste|Claude Code first" \
  README.md CHANGELOG.md docs install.sh scripts tests src
```

Read the diff itself. Confirm:

- no `eval`, `shell=True`, or command construction from saved text;
- neither absolute gate discovers, prompts, saves, or launches;
- normal output hides private paths while dry-run and verbose remain truthful;
- both installer forms call the same installed Python module;
- current v0.1.10 claims remain historical and accurate; and
- no version, signature, release URL, website source, or live route changed.

### Step 6: Commit the status record

```bash
git add docs/STATUS.md
git commit -m "docs: record unreleased harness-neutral handoff"
```

### Step 7: Perform GitHub preflight, push, and update the draft PR

```bash
getent hosts github.com
gh auth status --hostname github.com
gh api user --hostname github.com --jq '"GITHUB_OK: @" + .login'
git ls-remote origin HEAD
git status --short --branch
git push origin codex/lens-harness-routing-design
```

Update draft PR #40 to link:

- `docs/superpowers/specs/2026-08-26-dex-lens-harness-neutral-installer-handoff-design.md`
- `docs/superpowers/plans/2026-08-26-dex-lens-harness-neutral-installer-handoff.md`

After all checks pass, describe it as “implementation complete, release
closed,” include exact test counts and platform skips, and keep the PR draft.
Do not mark it ready, merge, tag, or publish.

### Step 8: Reconcile durable records without saying shipped

Follow the repository's Dispatch and Mission Control instructions. Record the
implementation milestone as ready for review. Do not mark the public installer
or website experience shipped.

---

## Later release hand-off (outside this plan)

Only after separate merge-and-release approval:

1. rerun release gates on the merge commit;
2. bump the version and changelog through the normal release process;
3. build and sign macOS arm64 and Linux x86_64 assets;
4. install each signed artifact fresh and repeat the one-adapter, two-adapter,
   remembered-choice, keyboard, and no-launch PTY proofs;
5. publish the release and update `heydex.ai/lens`;
6. prove the live installer is byte-identical to the intended signed artifact;
7. update website copy only after live behavior matches the approved words; and
8. close Mission Control and log one Dispatch shipped event with live evidence.

Until those steps happen, v0.1.10 and its current website wording remain the
public release truth.
