"""The bind-mount hostile fixture's payload, run inside a user namespace.

gates.md G1 fixture (2) and HANDOFF 5.1 require the **bind-mount** variant
of the symlink escape. A bind mount needs ``CAP_SYS_ADMIN`` in the user
namespace owning the mount namespace, and it is only visible inside the
mount namespace that created it — so it cannot be built in the pytest
process. This module is what
``unshare --user --map-root-user --mount python -m ...`` executes.

It does three things, in order:

1. builds the fixture layout and performs the escape —
   ``mount --bind <fake ~/.ssh> <approved-root>/vendor-cache`` on one
   device;
2. **proves the escape is real and is exactly the hole the audit found** —
   the canary is readable through the mount, ``st_dev`` is unchanged, and
   ``os.path.ismount`` says False. If those stop holding, the fixture is no
   longer testing the hole and says so instead of passing;
3. drives the real allowlist → snapshot → collector pipeline over the
   grafted root and reports, as JSON on stdout, every verdict and whether
   any canary byte survived into the snapshot or the envelope.

The parent test asserts on that report. Nothing here softens an assertion:
a mount that cannot be made exits :data:`EXIT_MOUNT_UNAVAILABLE` so the
parent skips *visibly*, and any unexpected error exits
:data:`EXIT_CHILD_ERROR` so the parent fails.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import traceback
from pathlib import Path

from tests.fixtures.hostile.catalog import (
    CANARY_BIND_MOUNT_BYTES,
    assert_no_canary_leak,
    build_bind_mount_escape_system,
)
from tests.fixtures.hostile.pipeline import collect_from, serialized, snapshot_of

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist

#: Report written to stdout, parent asserted.
EXIT_OK = 0
#: The bind mount could not be created here (no CAP_SYS_ADMIN in the user
#: namespace, hardened kernel, container policy). The parent turns this into
#: a visible skip carrying the kernel's own reason — never a silent pass.
EXIT_MOUNT_UNAVAILABLE = 3
#: Anything else. The parent fails on it.
EXIT_CHILD_ERROR = 4

_MS_BIND = 4096


def bind_mount(source: Path, target: Path) -> None:
    """``mount --bind source target`` via libc, no util-linux dependency."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    libc.mount.restype = ctypes.c_int
    ctypes.set_errno(0)
    status = libc.mount(
        os.fsencode(str(source)), os.fsencode(str(target)), None, _MS_BIND, None
    )
    if status != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), str(target))


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def _leaks(blob: str, canary: str) -> bool:
    try:
        assert_no_canary_leak(blob, [canary], context="bind-mount child")
    except AssertionError:
        return True
    return False


def main(argv: list[str]) -> int:
    system = build_bind_mount_escape_system(Path(argv[1]))
    try:
        bind_mount(system.fake_ssh_dir, system.mount_target)
    except OSError as exc:
        print(f"bind mount could not be created: {exc}", file=sys.stderr)
        return EXIT_MOUNT_UNAVAILABLE

    # (2) The escape must actually be the hole, or this fixture proves nothing.
    # Probed rather than asserted here: a mount that reported success but did
    # not take effect must reach the parent as a report it can fail on, not as
    # a traceback the parent has to interpret.
    grafted = os.stat(system.mount_target)
    root_stat = os.stat(system.root)
    escape = {
        "canary_readable_through_mount": CANARY_BIND_MOUNT_BYTES
        in _read_or_empty(system.mount_target / "id_ed25519"),
        "decoy_hidden_by_mount": not (system.mount_target / "index.md").exists(),
        "same_device_as_approved_root": grafted.st_dev == root_stat.st_dev,
        "ismount_says_no": not os.path.ismount(system.mount_target),
        "realpath_stays_inside_root": os.path.realpath(system.mount_target)
        == str(system.mount_target),
    }

    # (3) The real pipeline over the grafted root.
    allowlist = CanonicalAllowlist([str(system.root)])
    key_decision = allowlist.evaluate(system.mount_target / "id_ed25519")
    dir_decision = allowlist.evaluate(system.mount_target)
    outcome = allowlist.survey()

    _contract, snapshot = snapshot_of(system.root)
    snapshot_paths = snapshot.canonical_paths()
    envelope = collect_from(system.root)

    report = {
        "escape": escape,
        "mount_points_inside_scope": list(allowlist.mount_points_inside_scope),
        "key_decision": {"verdict": str(key_decision.verdict), "reason": key_decision.reason},
        "dir_decision": {"verdict": str(dir_decision.verdict), "reason": dir_decision.reason},
        "admitted_relative_paths": [d.relative_path for d in outcome.admitted_files],
        "exclusion_reasons": sorted({d.reason for d in outcome.excluded}),
        "snapshot_relative_paths": [
            os.path.relpath(path, str(system.root)) for path in snapshot_paths
        ],
        "canary_in_snapshot": any(
            _leaks(snapshot.content_of(path).decode("utf-8", "replace"), CANARY_BIND_MOUNT_BYTES)
            for path in snapshot_paths
        ),
        "canary_in_envelope": _leaks(serialized(envelope), CANARY_BIND_MOUNT_BYTES),
    }
    print(json.dumps(report))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    try:
        sys.exit(main(sys.argv))
    except Exception:  # noqa: BLE001 - the parent needs the whole traceback
        traceback.print_exc()
        sys.exit(EXIT_CHILD_ERROR)
