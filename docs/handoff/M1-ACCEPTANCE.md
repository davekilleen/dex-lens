# M1 Acceptance Verification (adversarial)

**Date:** 2026-08-07
**Scope:** HANDOFF.md Section 4, milestone **M1** — repo scaffold + adapter containment core + hostile fixture suite (diagnosis-only, no writes).
**Criteria source of truth:** `docs/handoff/sources/gates.md` (G1, G2, R2) plus HANDOFF Section 4's M1 conformance/zero-writes/no-mutating-entry-point clause.
**Method:** run every gate instrument, then attempt to break each criterion with probes written for this review — novel symlink variants, novel prompt-injection phrasings, uninventoried-field sneaks, a seccomp escape battery, and exhaustive R2 mapping enumeration. Findings were fixed test-first (failing test first, then the fix), and the whole suite re-run.

**Standing rule applied throughout: no criterion is marked MET without a passing test to cite, and — since HANDOFF Section 4 defines done as passing *in CI* — without that test passing in CI.** Where a criterion is provable only on one platform, the row says which CI leg establishes it.

---

## 1. Instrument results (recorded, not claimed)

Results below are from **CI**, not from a local run, because the criterion is that the gates pass in CI (HANDOFF Section 4) and because a version-specific failure (Finding F, §3.5) had been passing locally on Python 3.13 while failing on the 3.11/3.12 legs CI actually runs.

| Instrument | Command | Result (CI, **after** this review) | Result (CI, before this review) |
| --- | --- | --- | --- |
| Test suite | `python -m pytest` | **PASSED on all 4 legs** — 390 passed / 4 skipped (ubuntu), 378 passed / 16 skipped (macos-14) | **FAILED on all 4 legs** — see Finding F, §3.5 |
| Lint | `ruff check .` | **All checks passed** (4/4 legs) | passed |
| G2 inventory check | `python scripts/check_inventory.py` | **OK** — 73 inventoried fields, 11 stored (all with registered deletion paths), **0 transmitted**; browser/session state is explicitly inventoried | **never executed** (pytest step failed first) |
| Adapter conformance | `python -m capability_exchange.conformance --adapter claude-code-local --self-check` | **CONFORMANT: every check passed** (5/5) | **never executed** (pytest step failed first) |

**CI run [31182628679](https://github.com/davekilleen/dex-capability-exchange/actions/runs/31182628679) — `success` on all four legs** (`ubuntu-latest` × py3.11/3.12, `macos-14` × py3.11/3.12). This is the **first observed green CI run for M1**, and the first time `adapter-conformance-claude-code` and `g2-inventory-check` executed at all. Locally the suite was additionally run on Python 3.11, 3.12 and 3.13.

Conformance checks that passed: `contract-declaration-completeness` (G1), `zero-writes-proof` (G1), `result-envelope-conformance` (R2), `snapshot-semantics` (G1), `honest-fallback` (G1).

---

## 2. Per-criterion verdict table

### G1 — Constrained adapter containment, all six properties

| # | Property | Verdict | Proving tests |
| --- | --- | --- | --- |
| G1(a) | No arbitrary shell, no hooks, **no file writes**, no network egress from the inspection process | **MET on Linux; macOS deep inspection now fails closed unless socket creation is runtime-proven.** A runner that proves only connect-time denial uses the guided fallback; the shipped profile still denies writes/exec and the direct egress probe remains covered. | `tests/adapters/claude_code/test_containment.py::TestSeccompDeniesEvenBuggyCode::test_confined_process_cannot_socket_write_or_exec`, `::test_confined_process_cannot_write_file_metadata`; `tests/egress/test_g2_default_path_egress.py::TestSocketRefusalUnderSameStrategy`; macOS profile and fail-closed selection tests in `tests/egress/test_g2_macos_sandbox_profile.py` and `test_containment.py::TestStrategySelection` |
| G1(b) | Approved, canonicalized real-path allowlist | **MET** | `tests/adapters/claude_code/test_allowlist.py::TestConstruction` (6 tests), `::TestEvaluate` (13 tests incl. 2 **new**), `::TestSurvey` (5 tests) |
| G1(c) | All reads from an immutable consent-time snapshot | **MET** | `tests/adapters/claude_code/test_snapshot.py::TestSnapshotReads` (4), `::TestChangeDetection` (4); `tests/fixtures/hostile/test_g1_mutation_during_inspection.py` (4); conformance check `snapshot-semantics` |
| G1(d) | Explicit symlink / mount / ignored-file / credential / secret handling | **MET** | `tests/fixtures/hostile/test_g1_symlink_hardlink_escapes.py` (6 tests incl. 1 **new**); `tests/fixtures/hostile/test_g1_planted_secrets.py` (6); `tests/adapters/claude_code/test_secrets.py` (20, incl. 2 hypothesis property tests); `test_allowlist.py::test_mount_point_crossing_blocked`, `::test_gitignored_file_still_inspected` |
| G1(e) | Inspected file content is untrusted data — no instruction may alter behavior | **MET** | `tests/fixtures/hostile/test_g1_prompt_injection.py` (5, incl. byte-identical-envelope-vs-control); `tests/adapters/claude_code/test_collector.py::TestUntrustedContent` (2) |
| G1(f) | External model requests need separate explicit consent | **MET (vacuously, and structurally)** | `tests/fixtures/hostile/test_g1_external_model_requests.py` (6). At M1 no model client exists at all and none is importable; the test asserts absence structurally rather than asserting a consent gate that has nothing to gate |

**Zero scope escapes under the hostile suite:** confirmed. See §3 for the adversarial probes run beyond the shipped fixtures, and the G1(a) escapes they found and closed (Findings B and C).

### G2 — Field-level data boundary (foundation)

| Criterion | Verdict | Proving tests |
| --- | --- | --- |
| Machine-readable inventory in CI; a new persisted/transmitted field without an entry fails the build | **MET** | `tests/boundary/test_check_inventory.py` (6 tests incl. 1 **new**); `tests/boundary/test_inventory.py` (13); CI step `g2-inventory-check` |
| Typed serialization boundary — only inventoried fields serializable | **MET** | `tests/boundary/test_serialization.py` (12, incl. a hypothesis property test over arbitrary field names) |
| Default-path egress test with planted canaries shows zero unapproved raw **or derived** representation (incl. hashes/embeddings) | **MET** | `tests/egress/test_g2_default_path_egress.py::TestFullInspectionLeakFree` (3) — asserts canaries, substrings, **and sha256 derivations** absent; `::test_g2_two_runs_never_share_reference_digests` proves references are per-inspection-keyed, not unkeyed content hashes |
| Crash-log fixture contains no private field values | **MET** | `tests/boundary/test_crashlog.py` (7); `tests/egress/test_g2_default_path_egress.py::TestCrashOutputLeakFree` (3) |
| Every field's deletion path verifiably removes bytes | **MET** | `tests/boundary/test_deletion.py` (9) |

At M1 the inventory admits `sharing: never` only, so the approved-egress set is **empty** and the assertion is total (`test_packaged_inventory_permits_no_transmission_at_all`). Catalog refresh does not exist yet (blocked on D8).

### R2 — Machine-readable evidence and finding states

| Criterion | Verdict | Proving tests |
| --- | --- | --- |
| Closed state vocabulary, schema-enforced | **MET** | `tests/evidence/test_states.py` (11, incl. 2 hypothesis property tests asserting arbitrary text always lands inside the closed vocabulary) |
| Every finding carries state + source age + non-raw reference | **MET** | `tests/evidence/test_item.py` (30 tests incl. 5 **new**); conformance check `result-envelope-conformance` |
| A "reference" containing raw file content fails validation | **MET** | `test_item.py::TestNonRawReference` (9) plus **new** `::TestValidationBypassRoutes` (4) closing the `model_construct` / `model_copy` validation-skip routes |
| `absent` / `not assessed` never display or count as passing | **MET** | `test_states.py::TestSupportsNothing` (4); `tests/adapter/test_envelope.py::TestBrokenInstrumentNeverSuccess` (2) |
| **Total R2 → Evidence Level mapping ships with the vocabulary and passes its property test** | **MET** | `tests/evidence/test_levels.py` (16). `::test_exhaustive_every_combination_maps_to_exactly_one_level` enumerates **all 2^11 = 2048 state combinations**; `::TestNeverVerified` (3) proves the six never-Verified states never reach Verified in any combination. Independently re-verified in this review across **4096** cases (2048 combinations × 2 supply modes): zero soundness violations, zero monotonicity violations |

### M1 conformance / zero-writes / no-mutating-entry-point clause

| Criterion | Verdict | Proving tests |
| --- | --- | --- |
| Conformance suite runs green on benign fixtures | **MET** | `tests/conformance/test_claude_code_conformance.py::TestFullSuite` (4); CI step `adapter-conformance-claude-code` |
| Suite proves **zero writes** (file tracing) during any inspection | **MET** | `TestFullSuite::test_g1_zero_writes_proof_over_secret_bearing_system`; witness is `tree_identity` (content SHA-256, size, mode, mtime_ns, dir entry sets, symlink targets, **and xattrs** — xattrs added by this review) |
| The suite can actually fail (instrument validity) | **MET** | `TestSuiteCatchesViolations` (5 tests incl. 1 **new**) — deliberately sabotaged subjects must be caught, including a **metadata-only (xattr) write** that leaves content and stat identical |
| Diagnosis toolset contains **no mutating entry point**; model-facing surface is read/preview/status only | **MET** | `tests/adapter/test_surface.py::TestStructuralReadOnlyAssertion` (7) and `::TestReadPreviewStatus` (8); `tests/adapters/claude_code/test_surface_read_only.py` (4). The scan runs at package import and again in tests, over both `capability_exchange.adapter` and all 8 `adapters.claude_code` modules |
| Fail closed: containment unprovable → deep adapter disabled, honest guided/export-assisted fallback | **MET** | `test_containment.py::TestStrategySelection` (4), `::TestChildProtocolFailClosed` (3), `::TestTestStrategyDiscipline` (2); conformance check `honest-fallback` |
| Runtime ambiguity aborts inspection and discards partials | **MET** | `test_snapshot.py::TestFailClosed` (2), `::test_recheck_ambiguity_aborts_and_discards`; `tests/fixtures/hostile/test_g1_mutation_during_inspection.py::test_g1_detection_ambiguity_aborts_and_discards` |
| R7 initial data-flow and trust-boundary diagrams | **MET (artifact exists; R7 completeness is an M6 criterion)** | `docs/architecture.md` — trust-boundary diagram plus the M1 slice walkthrough |

---

## 3. Adversarial probes run for this review, and what they found

Five probe families were written specifically to break M1. Three found nothing; two found real defects, all now fixed test-first.

### 3.1 Novel symlink / path-escape variants — **no escape**

Eleven variants beyond the shipped fixtures: two-hop symlink chain, relative `../` traversal link, dangling link, link to `/proc/self/environ`, link to `/dev/urandom`, directory-symlink pointing out of scope, a path resolved *through* that directory symlink, link to `/etc/passwd`, in-scope link, self-referential loop, and a link to `/`. **All eleven were contained** (`blocked/symlink-escape` or equivalent); no out-of-scope content reached the snapshot or the envelope in any variant.

**Finding A (availability, fixed):** two of them — dangling symlink and symlink self-loop — aborted the *entire* inspection via `InspectionAbortedError`. That fails in the safe direction, but a broken symlink is ordinary in real systems and trivial to plant, so any inspected system could deny itself the deep adapter with one `ln -s` — a G1 downgrade the person never chose. `ENOENT` and `ELOOP` are unambiguous answers, not runtime ambiguity. Fixed: dangling → `absent` / `dangling-symlink`, loop → `blocked` / `symlink-loop`, both honest per-path exclusions, inspection continues. Ambiguity is now reserved for genuinely uncertain outcomes (races, unexpected errors), which still abort.
Tests: `test_allowlist.py::test_dangling_symlink_is_absent_not_ambiguous`, `::test_symlink_loop_is_blocked_not_ambiguous`, `test_g1_symlink_hardlink_escapes.py::test_g1_broken_links_do_not_disable_the_adapter`.

### 3.2 Novel prompt-injection phrasings — **no escape**

Ten phrasings not in the shipped corpus: role-prefix (`SYSTEM:`) transcript shape, tool-call-shaped JSON, base64-wrapped instruction, YAML front-matter directive, Cyrillic-homoglyph + RTL-override text, zero-width-joiner obfuscation, multilingual (French + Chinese), markdown-link exfil with command substitution, XML function-call tags, and ANSI escape sequences — plus an **injection embedded in a file name**.

Result: probe ids, instrument health, captured-file count, and scope were **identical to the control run**; no injection text and no attacker-controlled filename appeared anywhere in the envelope; every captured path stayed under the approved root. The adapter never decodes or interprets content — it treats bytes as bytes — so this class does not depend on phrasing coverage.

### 3.3 Seccomp escape battery — **two real escapes found and closed**

~40 operations attempted from inside the real confinement: all socket families (INET/INET6/UNIX/NETLINK/PACKET, socketpair, pre-confinement socket reuse), exec paths (`posix_spawn`, `execv`, `fork`-then-`exec`), the full filesystem-mutation set, and raw `openat2` / `io_uring_setup` syscalls. Sockets, exec, `mkdir`/`unlink`/`rename`/`link`/`symlink`/`chmod`/`chown`/`truncate`/`mknod`/`chroot`, every write-capable `open` flag, `openat2` and `io_uring_setup` were all correctly denied (EPERM).

**Finding B (containment escape, fixed) — metadata writes were possible.** `os.utime` **changed a file's mtime on disk** and `os.setxattr` / `os.removexattr` **set and removed extended attributes on disk**, all under full confinement. Root cause: the open-flag BPF check gates write capability *acquired through `open`*, but `utimensat` and the `*xattr` family take a path (or a read-only fd) and mutate a file without ever opening it for writing, so they bypassed the gate entirely. Timestamps and xattrs are part of the person's system, so this is a G1(a) "no file writes" violation against the stated bar ("even if its own code is buggy").
Fixed: added `utime`/`utimes`/`futimesat`/`utimensat`, the six `*setxattr`/`*removexattr` syscalls, plus `mount`/`umount2`/`fallocate` to the denied tables for **both** x86_64 and aarch64. Verified: all now EPERM, mtime and xattrs unchanged.
Test: `test_containment.py::TestSeccompDeniesEvenBuggyCode::test_confined_process_cannot_write_file_metadata`.

**Finding C (blind instrument, fixed) — the zero-writes witness could not see Finding B.** `tree_identity` captured content, size, mode, mtime and symlink targets but **not extended attributes**, so an xattr-only write left the tree "byte-identical" and the conformance suite reported `zero-writes-proof: PASSED` while the inspected system had in fact been modified. Two independent layers missed the same write. Fixed: xattrs (name + SHA-256 of value, `follow_symlinks=False`) are now part of the witness, degrading cleanly to empty on filesystems without xattr support.
Test: `test_claude_code_conformance.py::TestSuiteCatchesViolations::test_g1_detects_a_metadata_only_write_during_inspection`.

### 3.4 Uninventoried-field sneaks — **one real gap found and closed**

Six routes attempted: subclassing `EvidenceItem` with an extra field (refused), a pydantic `TypeAdapter` route around the `model_dump` override (refused), `model_construct` with a raw PEM reference, a plain dataclass `json.dumps`, `__dict__` `json.dumps`, and a **class-name collision**.

**Finding D (G2 gap, fixed) — the inventory namespace could be captured by collision.** Inventory keys are bare `ClassName.field`, and both the runtime boundary and `check_inventory.py` keyed on `cls.__name__`. A second `InventoriedModel` reusing an inventoried model's class name silently inherited its entries and serialized a field that was never inventoried — the CI check reported **zero problems** while an impostor `EvidenceItem` serialized `EXFILTRATED-PRIVATE-PAYLOAD`. "Every field has an inventory entry" was satisfiable by collision rather than by declaration. Fixed: `check_inventory.py` now fails the build on any duplicate `InventoriedModel` class name, naming both modules.
Test: `test_check_inventory.py::test_class_name_collision_is_a_problem`.

**Finding E (R2 consistency, fixed) — `model_construct` bypassed the non-raw-reference validator,** letting raw key material be smuggled into an `EvidenceItem.reference` and serialized. The codebase already closes exactly these routes on `AdapterContract` (`model_construct` and `model_copy` overrides), so this was an inconsistency rather than an oversight in design. Fixed with the same pattern on `EvidenceItem`.
Tests: `test_item.py::TestValidationBypassRoutes` (4).

### 3.5 CI reality check — **M1 was not passing in CI at all (Finding F, fixed)**

HANDOFF Section 4 is explicit: *"A milestone is done when its listed criteria pass in CI, not when its features demo."* So the CI state is itself an acceptance criterion, and it was red.

`gh run list` showed the **pre-existing** `main` run (`31180012038`, commit `e333c99`) had **failed on all four matrix legs**, as had an earlier attempted fix branch. Every leg died in `Test (pytest)` before `adapter-conformance-claude-code` or `g2-inventory-check` ever ran — so on the evidence available in CI, **none of the three gate instruments had ever been observed green there**. A local green run had been standing in for a CI green run.

Root cause: `test_allowlist.py::test_mount_point_crossing_blocked` patches `os.stat` globally and then called `str(path)` and `target.resolve()` *inside* the patched function. Both re-enter pathlib, which calls `os.stat`, which is the patch — unbounded recursion (`RecursionError`, plus `'PosixPath' object has no attribute '_str'` as pathlib's half-initialised internals surfaced). It passes on Python 3.13, whose pathlib internals differ, and fails on 3.11 and 3.12 — which is exactly the matrix CI runs and the local `.venv` (3.13) does not.

Fixed: every path value the shim needs is resolved to a plain `str` **before** the patch is installed; the shim compares strings only and never touches pathlib; and it returns a genuine `os.stat_result` (built with a modified `st_dev`, preserving the `*_ns` fields) instead of a `__getattr__` attribute proxy. Reproduced the failure and verified the fix locally on **3.11, 3.12 and 3.13**: 384 passed, 4 skipped on each.

This is the finding with the widest blast radius, because it means the milestone's own completion signal was unverified. It also explains why the darwin-only assertions in §4 had never actually run: the macOS legs failed at the same point.

### 3.6 Hostile file *names* — **one real defect found and closed (Finding G)**

With the CI legs finally running, an existing hypothesis property test — `test_g1_any_relative_path_yields_a_valid_reference_token`, written precisely to assert this invariant — generated the example `-----BEGIN` and failed.

`reference_token` guards a candidate name for length, space count and control characters, but **not** for the `-----BEGIN` key-block marker that `EvidenceItem`'s reference validator independently rejects. So a file named `-----BEGIN` (or any name containing it) produced a token the builder passed through and the schema then refused, raising `ValidationError` **mid-collection**. In the contained child that surfaces as `EXIT_COLLECTION_FAILED` — "collection aborted; partials discarded". One oddly-named file in the inspected scope disabled the entire deep adapter: the same availability weapon as Finding A, and a direct contradiction of `reference_token`'s own docstring promise that "a hostile file name must never be able to poison a reference and abort the inspection".

Root cause is the shape worth naming: **a producer and a consumer of the same value each carried their own nearly-identical copy of the rule, and they drifted.** Fixed by making the rule single-sourced — the schema's predicate is now public (`reference_rejection_reason`) and `reference_token` consults it directly instead of restating it, so a producer fails closed on exactly what the consumer rejects. Pinned with a deterministic regression test over three marker-bearing names, and the property test's budget raised from 50 to 500 examples.

Verified end-to-end: a tree containing files named `-----BEGIN` and `-----BEGIN RSA PRIVATE KEY-----` now collects all four files, produces all five probes, and leaks no marker into the envelope.

Two notes on process. First, this bug was **latent in the shipped suite** — the property test existed and would have caught it on any run that happened to generate the example; at 50 examples over a 255-character text space it rarely did. Property-test budgets are themselves an acceptance parameter. Second, it was only observable because Finding F was fixed first: while CI was red at the pytest step, no amount of property testing was running there at all.

### 3.7 R2 → Evidence Level mapping — **no unsoundness**

Independently re-enumerated all 2048 state combinations × 2 supply modes = **4096 cases**. Every case returned exactly one `EvidenceLevel`. Zero cases reached `Verified` while containing a never-Verified state, while `user_supplied_material=True`, or without `observed`. Adding any degraded state never *raised* the level (monotonicity holds). `absent` and `not-assessed` alone both map to `Unknown`.

### 3.8 macOS containment — **connect-time proof is not socket-object proof; deep inspection now fails closed**

Fixing Finding F let the macOS legs run for the first time, and they immediately failed — twice over, each failure having been masked by the one in front of it.

**First: the framework-Python exec-set gap.** Every contained collection died with `posix_spawn: .../Resources/Python.app/Contents/MacOS/Python: Undefined error: 0`. A python.org **framework** build is not one binary: `sys.executable` is a launcher under `bin/`, its realpath is the versioned binary beside it, and the framework re-execs a *third* path during start-up. The profile enumerated only the first two, so the child was denied exec of itself before it ran — surfacing as a containment failure rather than as the profile gap it was. A fix existed on the unmerged `fix/m1-ci-green` branch but **had never been CI-tested** (the branch's last run predated it); it was reviewed, cherry-picked onto `main`, and is now verified green. It adds a third enumerated literal (`PYAPP`) rather than a subpath over `sys.prefix` — G1's guarantee is an enumerated exec set, not a trusted directory, and none of the three is a shell. That commit also fixed a third instance of the Finding C pattern: the test had built its own copy of the `-D` arguments, so the profile could pass its own test while the real child died.

**Second: a Linux-shaped assertion.** With containment working, two end-to-end tests still failed asserting the proof label `socket-denied`. That label is Linux-specific: seccomp denies `socket()` outright, whereas `sandbox-exec`'s `(deny network*)` lets the fd be allocated and denies `connect`, so a correctly contained macOS run honestly reports `connect-denied`. Either proves no egress — egress needs `connect`/`sendto`, and `prove_containment` raises if a connection actually succeeds. A third test in the same file already accepted either label; the two end-to-end tests now match it. This is a test correction, not a weakened egress guarantee. M3 closure adds a runtime availability check requiring the full G1 tuple, including `socket-denied`; a host that returns only `connect-denied` is refused before any target read and receives the guided/export-assisted path. No-egress, no-write, and no-exec remain required on every host that runs the deep adapter.

A third failure in that run was mine: the new metadata-only-write conformance test called `os.setxattr`, which is Linux-only in CPython and raises `AttributeError` rather than `OSError`, so my existing guard missed it. It now skips where the wrappers are absent.

---

## 4. PARTIAL / GAP items, stated honestly

| Item | Status | Reason |
| --- | --- | --- |
| **macOS `sandbox-exec` containment enforcement** | **PARTIAL / fail-closed by design** | The historical M1 run [31182628679](https://github.com/davekilleen/dex-capability-exchange/actions/runs/31182628679) proved connect-time egress denial plus write/exec denial on `macos-14`, but it did **not** prove socket-object denial. M3 now refuses the deep adapter on that evidence shape unless a fresh runtime probe returns `socket-denied`; no target read occurs and the guided/export-assisted path is explicit. A future Darwin CI artifact with the full tuple may promote this row. |
| **Linux seccomp syscall table for non-x86_64/aarch64** | **By design: fail closed** | Any other architecture raises `ConfinementError` → deep adapter disabled with the guided fallback. Tested via `LinuxStrategy.availability()`. No silent uncontained collection |
| **aarch64 syscall numbers** | **PARTIAL — not executed on any CI leg** | The aarch64 denied table (including the syscalls added by Finding B) is asserted by inspection against the asm-generic table, not by execution. The CI matrix runs x86_64 Linux and arm64 macOS; **no arm64 Linux leg exists**, so the aarch64 BPF table is unexercised. Low risk (a wrong number fails closed at filter-install or is caught by the runtime probes), but it is not proven |
| **Egress proof is syscall-level, not packet-level, at M1** | **Adequate for M1, by the pack's own schedule** | HANDOFF 5.2 schedules OS-level packet capture at M3 "when a real journey exists"; at M1 the socket layer is the wire, and the process is proven incapable of creating a socket at all. `tests/egress/harness.py` documents this explicitly |
| **G2 boundary covers pydantic models, not arbitrary Python objects** | **Bounded residual** | `check_inventory.py` fails the build on any pydantic model that is not an `InventoriedModel`, and M3's browser/session state now has a dedicated `ConciergeSessionState` model with six explicit inventory declarations. A plain dataclass `json.dumps`'d would still not be caught; no browser/session field is allowed to persist or transmit by default. |
| **TOCTOU on an intermediate directory component** | **Residual, documented** | Reads use `O_NOFOLLOW`, which protects the final component; a sufficiently fast attacker swapping an *intermediate* directory for a symlink between `realpath` and `open` is not structurally excluded. Mitigated by device-boundary checks, the immutable snapshot, and the mid-inspection integrity recheck (digest **and** mtime, ABA-aware). Closing it properly needs `openat2(RESOLVE_BENEATH)` — which is currently *denied* by the filter as an uninspectable side door. Worth an explicit M3 decision |
| **G1(f) external-model consent** | **MET vacuously** | No model client exists or is importable at M1, which is proven structurally. The *consent gate itself* is unimplemented because there is nothing to gate; it becomes a live criterion at D8/M2 |
| G3, G4, G5, G6, R1, R3, R5, R6, R7, T1–T9, P1 | **Not in scope for M1** | Scheduled M2–M6 per HANDOFF Section 4. No M1 claim is made about them |

---

## 5. Overall M1 verdict

**M1 is MET.** Every listed M1 acceptance criterion passes in CI — the milestone's own definition of done — on all four matrix legs, including both `macos-14` legs.

This verdict was **not** available when the review began: CI was red on every leg, and the state it was in would not have supported this claim. It became available only after seven defects were fixed.

Grounds:

- **CI run [31182628679](https://github.com/davekilleen/dex-capability-exchange/actions/runs/31182628679) is green on all four legs**, with `pytest`, `adapter-conformance-claude-code` (5/5 checks CONFORMANT) and `g2-inventory-check` (27 fields, 0 transmitted) all executing and passing on **both** ubuntu-latest and macos-14. This is the first such run in the project's history.
- Every M1 acceptance criterion in HANDOFF Section 4 — G1's six containment properties, G2's foundation, R2 including the total Evidence Level mapping property test, and the conformance / zero-writes / no-mutating-entry-point clause — has at least one passing, cited test. None is asserted on inspection alone.
- The adversarial pass found **seven defects**: two genuine containment/boundary escapes (B, D), one **blind instrument** that concealed one of them (C), three correctness/availability defects (A, E, G), and one that the milestone's own completion signal had never been green (F). All seven are fixed, each with a test that failed before the fix and passes after. The suite went 374 → 390 tests, verified on Python 3.11, 3.12 and 3.13 locally and on 3.11/3.12 × 2 platforms in CI.
- Three probe families found nothing: eleven novel path-escape variants, ten novel injection phrasings including filename injection, and 4096 exhaustively enumerated R2 mapping cases.

Honest qualifications — these do not block the verdict but should travel with it:

1. **This verdict rests on a CI run, and must be re-read against CI, not locally.** The macOS half of G1(a) is unreproducible on Linux; a reviewer running the suite locally on Linux will see 4 skips there and cannot confirm that row.
2. **Finding C is the most instructive result of this review.** A conformance suite that reports `zero-writes-proof: PASSED` over a tree that was in fact modified is worse than no proof: it converts an unknown into a false assurance. The suite's `TestSuiteCatchesViolations` class is what caught it, and that pattern — deliberately sabotaged subjects proving the instrument can fail — should be mandatory for every gate instrument added in M2–M6, not optional.
3. **Two independent layers missed the same class of write** (metadata mutation). That is a correlated-failure signal: both reasoned about writes as "content changes acquired through `open`". Future gate work should enumerate the mutation surface from the syscall table rather than from an intuition about what a write is.
4. Findings C and F share a shape worth naming: **an instrument that cannot fail, or never runs, reports the same thing as an instrument that passes.** Both were invisible to anyone reading only the green local output. The macOS profile fix cherry-picked into this branch fixed a third instance (its test built its own copy of the sandbox arguments, so the profile could pass its own test while the real child died).
5. Findings D and G share a different shape: **two places carrying near-duplicate copies of one rule, which then drifted** — the inventory key namespace, and the reference-validity rule split between producer and consumer. Both are now single-sourced.
6. **Property-test budgets are an acceptance parameter.** Finding G was catchable by a test already in the suite; at 50 examples it rarely generated the failing input. Raised to 500 here, but M2+ should set budgets deliberately per property rather than by default.
7. The aarch64 seccomp table remains unexercised by any CI leg. Adding an arm64 Linux runner would convert a reasoned assertion into a proof.
8. Nothing here speaks to M2–M6 gates, and per HANDOFF Section 4 the pilot's real-user automated adaptation still requires all six Fable gates green on the exact pilot build plus R6's red-team — none of which M1 provides.

**Recommendation:** M1 can be signed off against CI run [31182628679](https://github.com/davekilleen/dex-capability-exchange/actions/runs/31182628679). Carry the PARTIAL and residual items in §4 into the R7 unresolved-risk register with named owners (D7), and treat three practices from this review as standing requirements for M2–M6: every gate instrument ships with a sabotaged-subject test proving it can fail; rules enforced in two places are single-sourced; and no milestone is called done on a local run.
