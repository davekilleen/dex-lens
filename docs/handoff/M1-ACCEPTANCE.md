# M1 Acceptance Verification (adversarial)

**Date:** 2026-08-07
**Scope:** HANDOFF.md Section 4, milestone **M1** — repo scaffold + adapter containment core + hostile fixture suite (diagnosis-only, no writes).
**Criteria source of truth:** `docs/handoff/sources/gates.md` (G1, G2, R2) plus HANDOFF Section 4's M1 conformance/zero-writes/no-mutating-entry-point clause.
**Method:** run every gate instrument, then attempt to break each criterion with probes written for this review — novel symlink variants, novel prompt-injection phrasings, uninventoried-field sneaks, a seccomp escape battery, and exhaustive R2 mapping enumeration. Findings were fixed test-first (failing test first, then the fix), and the whole suite re-run.

**Standing rule applied throughout: no criterion is marked MET without a passing test to cite.** Where a criterion can only be proven on another platform, it is marked PARTIAL and says so.

---

## 1. Instrument results (recorded, not claimed)

Run on Linux x86_64, at the commit of this document. The suite was run under **Python 3.11, 3.12 and 3.13** — 384 passed, 4 skipped on each — because a version-specific failure (Finding F, §3.5) was passing locally on 3.13 while failing on the 3.11/3.12 legs CI actually runs.

| Instrument | Command | Result (local) | Result (CI, before this review) |
| --- | --- | --- | --- |
| Test suite | `python -m pytest` | **384 passed, 4 skipped** on py3.11/3.12/3.13 (skips are darwin-only, see §4) | **FAILED on all 4 legs** — see Finding F, §3.5 |
| Lint | `ruff check .` | **All checks passed** | passed |
| G2 inventory check | `python scripts/check_inventory.py` | **OK** — 27 inventoried fields, 4 stored (all with registered deletion paths), **0 transmitted** | **never executed** (pytest step failed first) |
| Adapter conformance | `python -m capability_exchange.conformance --adapter claude-code-local --self-check` | **CONFORMANT: every check passed** (5/5) | **never executed** (pytest step failed first) |

Conformance checks that passed: `contract-declaration-completeness` (G1), `zero-writes-proof` (G1), `result-envelope-conformance` (R2), `snapshot-semantics` (G1), `honest-fallback` (G1).

---

## 2. Per-criterion verdict table

### G1 — Constrained adapter containment, all six properties

| # | Property | Verdict | Proving tests |
| --- | --- | --- | --- |
| G1(a) | No arbitrary shell, no hooks, **no file writes**, no network egress from the inspection process | **MET (Linux) / PARTIAL (macOS)** | `tests/adapters/claude_code/test_containment.py::TestSeccompDeniesEvenBuggyCode::test_confined_process_cannot_socket_write_or_exec`, `::test_confined_process_cannot_write_file_metadata` (**new**); `tests/egress/test_g2_default_path_egress.py::TestSocketRefusalUnderSameStrategy` (both tests); `tests/fixtures/hostile/test_g1_external_model_requests.py::test_g1_no_model_client_or_egress_import_exists_in_the_package`. macOS half: `tests/egress/test_g2_macos_sandbox_profile.py` — **skipped on Linux**, see §4 |
| G1(b) | Approved, canonicalized real-path allowlist | **MET** | `tests/adapters/claude_code/test_allowlist.py::TestConstruction` (6 tests), `::TestEvaluate` (13 tests incl. 2 **new**), `::TestSurvey` (5 tests) |
| G1(c) | All reads from an immutable consent-time snapshot | **MET** | `tests/adapters/claude_code/test_snapshot.py::TestSnapshotReads` (4), `::TestChangeDetection` (4); `tests/fixtures/hostile/test_g1_mutation_during_inspection.py` (4); conformance check `snapshot-semantics` |
| G1(d) | Explicit symlink / mount / ignored-file / credential / secret handling | **MET** | `tests/fixtures/hostile/test_g1_symlink_hardlink_escapes.py` (6 tests incl. 1 **new**); `tests/fixtures/hostile/test_g1_planted_secrets.py` (6); `tests/adapters/claude_code/test_secrets.py` (20, incl. 2 hypothesis property tests); `test_allowlist.py::test_mount_point_crossing_blocked`, `::test_gitignored_file_still_inspected` |
| G1(e) | Inspected file content is untrusted data — no instruction may alter behavior | **MET** | `tests/fixtures/hostile/test_g1_prompt_injection.py` (5, incl. byte-identical-envelope-vs-control); `tests/adapters/claude_code/test_collector.py::TestUntrustedContent` (2) |
| G1(f) | External model requests need separate explicit consent | **MET (vacuously, and structurally)** | `tests/fixtures/hostile/test_g1_external_model_requests.py` (6). At M1 no model client exists at all and none is importable; the test asserts absence structurally rather than asserting a consent gate that has nothing to gate |

**Zero scope escapes under the hostile suite:** confirmed. See §3 for the adversarial probes run beyond the shipped fixtures, and the two G1(a) escapes they found and closed.

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

### 3.6 R2 → Evidence Level mapping — **no unsoundness**

Independently re-enumerated all 2048 state combinations × 2 supply modes = **4096 cases**. Every case returned exactly one `EvidenceLevel`. Zero cases reached `Verified` while containing a never-Verified state, while `user_supplied_material=True`, or without `observed`. Adding any degraded state never *raised* the level (monotonicity holds). `absent` and `not-assessed` alone both map to `Unknown`.

---

## 4. PARTIAL / GAP items, stated honestly

| Item | Status | Reason |
| --- | --- | --- |
| **macOS `sandbox-exec` containment enforcement** | **PARTIAL — provable only on darwin CI** | `MacOSStrategy` and the shipped `claude_code_containment.sb` profile cannot be executed on Linux. 4 tests skip here: `test_containment.py::TestMacOSContainedCollection::test_end_to_end_contained_or_honest_refusal` and the 3 in `tests/egress/test_g2_macos_sandbox_profile.py`. They are **not** skipped on darwin — the CI matrix (`ubuntu-latest`, `macos-14` × py3.11, py3.12) runs them, and `default_strategy()` on darwin returns `MacOSStrategy` or refuses. **This criterion is MET only when the macOS matrix leg is green**; Linux-local runs cannot establish it. Note the Fable critique's own rule applies: an unproven G1 on a host downgrades that host to guided/export-assisted rather than blocking the pilot, and that downgrade path is itself tested (`honest-fallback`, `TestStrategySelection`) |
| **Linux seccomp syscall table for non-x86_64/aarch64** | **By design: fail closed** | Any other architecture raises `ConfinementError` → deep adapter disabled with the guided fallback. Tested via `LinuxStrategy.availability()`. No silent uncontained collection |
| **aarch64 syscall numbers** | **PARTIAL — not executed on this host** | The aarch64 denied table (including the syscalls added by Finding B) is asserted by inspection against the asm-generic table, not by execution. The CI matrix runs x86_64 Linux and arm64 macOS; **no arm64 Linux leg exists**, so the aarch64 BPF table is unexercised. Low risk (a wrong number fails closed at filter-install or is caught by the runtime probes), but it is not proven |
| **Egress proof is syscall-level, not packet-level, at M1** | **Adequate for M1, by the pack's own schedule** | HANDOFF 5.2 schedules OS-level packet capture at M3 "when a real journey exists"; at M1 the socket layer is the wire, and the process is proven incapable of creating a socket at all. `tests/egress/harness.py` documents this explicitly |
| **G2 boundary covers pydantic models, not arbitrary Python objects** | **Bounded residual** | `check_inventory.py` fails the build on any pydantic model that is not an `InventoriedModel`, but a plain dataclass `json.dumps`'d would not be caught. Bounded at M1 because there is exactly one persistence path (crash log, an `InventoriedModel`) and **zero** transmission paths (`sharing: never` is the only value the schema admits). Should be revisited when M3 adds a browser/session store |
| **TOCTOU on an intermediate directory component** | **Residual, documented** | Reads use `O_NOFOLLOW`, which protects the final component; a sufficiently fast attacker swapping an *intermediate* directory for a symlink between `realpath` and `open` is not structurally excluded. Mitigated by device-boundary checks, the immutable snapshot, and the mid-inspection integrity recheck (digest **and** mtime, ABA-aware). Closing it properly needs `openat2(RESOLVE_BENEATH)` — which is currently *denied* by the filter as an uninspectable side door. Worth an explicit M3 decision |
| **G1(f) external-model consent** | **MET vacuously** | No model client exists or is importable at M1, which is proven structurally. The *consent gate itself* is unimplemented because there is nothing to gate; it becomes a live criterion at D8/M2 |
| G3, G4, G5, G6, R1, R3, R5, R6, R7, T1–T9, P1 | **Not in scope for M1** | Scheduled M2–M6 per HANDOFF Section 4. No M1 claim is made about them |

---

## 5. Overall M1 verdict

**M1 is NOT YET DONE by its own definition — pending a green CI run. On the code and test evidence it is otherwise MET on Linux, with the darwin half of G1(a) provable only on the macOS matrix legs.**

The distinction is deliberate and is the honest reading of HANDOFF Section 4: *"A milestone is done when its listed criteria pass in CI."* Before this review, CI was red on every matrix leg and had never been observed green (Finding F). That has now been fixed and verified locally across all three Python versions, but **the verdict below should be upgraded only once the pushed run is actually green** — this document must not repeat the mistake it documents by substituting a local run for a CI run.

Grounds for the substantive verdict:

- Every M1 acceptance criterion in HANDOFF Section 4 — G1's six containment properties, G2's foundation, R2 including the total Evidence Level mapping property test, and the conformance / zero-writes / no-mutating-entry-point clause — has at least one passing, cited test. None is asserted on inspection alone.
- The adversarial pass found **six defects**: two genuine containment/boundary escapes (B, D), one **blind instrument** that concealed one of them (C), two correctness/availability defects (A, E), and one that the milestone's own completion signal was never green (F). All six are fixed, each with a test that failed before the fix and passes after. The suite went 374 → 384 tests.
- Three probe families found nothing: eleven novel path-escape variants, ten novel injection phrasings including filename injection, and 4096 exhaustively enumerated R2 mapping cases.

Honest qualifications:

1. **CI must be green before M1 is signed off.** Finding F means the three gate instruments (`pytest`, `adapter-conformance-claude-code`, `g2-inventory-check`) had never been observed passing in CI — the latter two never even executed, because the pytest step failed first. A local green run is not the criterion.
2. **The macOS enforcement half of G1(a) is not provable on Linux,** and because of Finding F it has never run anywhere. Until the `macos-14` legs are green, darwin containment rests on a shipped profile and a strategy that nothing has exercised.
3. **Finding C is the most instructive result of this review.** A conformance suite that reports `zero-writes-proof: PASSED` over a tree that was in fact modified is worse than no proof: it converts an unknown into a false assurance. The suite's `TestSuiteCatchesViolations` class is what caught it, and that pattern — deliberately sabotaged subjects proving the instrument can fail — should be mandatory for every gate instrument added in M2–M6, not optional.
4. **Two independent layers missed the same class of write** (metadata mutation). That is a correlated-failure signal: both reasoned about writes as "content changes acquired through `open`". Future gate work should enumerate the mutation surface from the syscall table rather than from an intuition about what a write is.
5. Findings C and F share a shape worth naming: **an instrument that cannot fail, or never runs, reports the same thing as an instrument that passes.** Both were invisible to anyone reading only the green local output.
6. The aarch64 seccomp table remains unexercised by any CI leg. Adding an arm64 Linux runner would convert a reasoned assertion into a proof.
7. Nothing here speaks to M2–M6 gates, and per HANDOFF Section 4 the pilot's real-user automated adaptation still requires all six Fable gates green on the exact pilot build plus R6's red-team — none of which M1 provides.

**Recommendation:** hold M1 sign-off until the CI run on `main` is green on all four matrix legs; then treat M1 as complete on Linux with the darwin legs as the macOS evidence, and carry the six PARTIAL/residual items in §4 into the R7 unresolved-risk register with named owners (D7).
