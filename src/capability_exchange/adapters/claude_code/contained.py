"""The contained collection child process (gates.md G1 item a).

This module is the ``python -m`` entry point the containment strategies
launch. Inside this process the whole inspection happens under OS-level
enforcement — not convention:

- **Linux (self-confinement):** a seccomp BPF filter installed before any
  target read denies socket-family syscalls (no network egress), ``execve``
  / ``execveat`` (no shell spawning), write-capable ``open`` flags and the
  filesystem-mutation syscalls (no writes), plus ``openat2`` and
  ``io_uring_setup`` (uninspectable side doors). A network namespace is
  additionally unshared where the kernel permits (belt and braces).
- **macOS (external confinement):** the parent wraps this process in
  ``sandbox-exec`` with the shipped profile denying network, file writes,
  and process-exec of anything but the Python interpreter itself.

Either way, the process then **proves** its own containment with runtime
probes (socket, write-open of ``/dev/null``, exec of ``/bin/sh``) before
touching the approved scope. If containment cannot be proven, it exits with
:data:`EXIT_CONTAINMENT_UNAVAILABLE` having read nothing — the deep adapter
is then disabled for this host and the guided/export-assisted fallback is
reported honestly (G1 fail-closed rule). Any later failure exits with
:data:`EXIT_COLLECTION_FAILED`; partials live only in this process's memory
and die with it — they are discarded, never emitted.

Output protocol (stdout, single JSON object)::

    {"schema": "contained-collection-result/1",
     "layers": ["seccomp-filter", ...],
     "proofs": ["socket-denied", ...],
     "envelope": {...AdapterResultEnvelope...}}
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import json
import os
import platform
import socket
import struct
import sys

__all__ = [
    "EXIT_COLLECTION_FAILED",
    "EXIT_CONTAINMENT_UNAVAILABLE",
    "EXIT_OK",
    "REQUEST_SCHEMA",
    "RESULT_SCHEMA",
    "ConfinementError",
    "confine_this_process",
    "main",
    "prove_containment",
]

EXIT_OK = 0
EXIT_COLLECTION_FAILED = 70
EXIT_CONTAINMENT_UNAVAILABLE = 86

REQUEST_SCHEMA = "contained-collection-request/1"
RESULT_SCHEMA = "contained-collection-result/1"


class ConfinementError(Exception):
    """OS-level confinement could not be established or proven."""


# ---------------------------------------------------------------------------
# Linux seccomp confinement (classic-BPF filter assembled per-arch)
# ---------------------------------------------------------------------------

_PR_SET_NO_NEW_PRIVS = 38
_PR_SET_SECCOMP = 22
_SECCOMP_MODE_FILTER = 2

_BPF_LD_W_ABS = 0x20
_BPF_JEQ_K = 0x15
_BPF_JSET_K = 0x45
_BPF_RET_K = 0x06

_RET_ALLOW = 0x7FFF0000
_RET_KILL = 0x00000000
_RET_EPERM = 0x00050000 | errno.EPERM

#: open(2)-family flags that imply write capability (linux generic ABI):
#: O_WRONLY | O_RDWR | O_CREAT | O_TRUNC | O_APPEND | __O_TMPFILE.
#: Deliberately the bare __O_TMPFILE bit (0o20000000), not glibc's O_TMPFILE
#: composite — the composite includes O_DIRECTORY, which read-only directory
#: opens (os.scandir) legitimately use.
_WRITE_OPEN_FLAGS = 0o1 | 0o2 | 0o100 | 0o1000 | 0o2000 | 0o20000000

#: Per-arch syscall tables: denied outright, and open-family flag checks
#: as (syscall_nr, index of the flags argument).
#:
#: Note on completeness: the open-flag checks gate write capability that is
#: *acquired through open*, but several syscalls mutate a file by path (or
#: through a read-only fd) and never open it for writing — notably the
#: ``utime``/``utimensat`` and ``*xattr`` families. Timestamps and extended
#: attributes are part of the person's system, so G1(a)'s "no file writes"
#: covers them and they are denied outright here.
_ARCH_TABLES: dict[str, dict[str, object]] = {
    "x86_64": {
        "audit_arch": 0xC000003E,
        "denied": (
            41, 42, 43, 44, 46, 49, 50, 53, 288, 307,  # socket family
            59, 322,  # execve, execveat
            76, 77, 82, 83, 84, 85, 86, 87, 88,  # truncate..symlink
            90, 91, 92, 93, 94, 133, 161,  # chmod/chown family, mknod, chroot
            258, 259, 260, 263, 264, 265, 266, 268, 316,  # *at mutations
            132, 235, 261, 280,  # utime, utimes, futimesat, utimensat
            188, 189, 190, 197, 198, 199,  # *setxattr, *removexattr
            165, 166, 285,  # mount, umount2, fallocate
            437, 425,  # openat2 (uninspectable), io_uring_setup
        ),
        "open_flag_checks": ((2, 1), (257, 2)),  # open, openat
    },
    "aarch64": {
        "audit_arch": 0xC00000B7,
        "denied": (
            198, 199, 200, 201, 202, 203, 206, 211, 242, 269,  # socket family
            221, 281,  # execve, execveat
            33, 34, 35, 36, 37, 38, 276,  # mknodat..renameat, renameat2
            45, 46, 52, 53, 54, 55,  # truncate/ftruncate/chmod/chown family
            39, 40, 51,  # umount2, mount, chroot
            88,  # utimensat (no legacy utime/utimes/futimesat on aarch64)
            5, 6, 7, 14, 15, 16,  # *setxattr, *removexattr
            47,  # fallocate
            437, 425,  # openat2 (uninspectable), io_uring_setup
        ),
        "open_flag_checks": ((56, 2),),  # openat
    },
}


def _bpf_stmt(code: int, k: int) -> bytes:
    return struct.pack("HBBI", code, 0, 0, k)


def _bpf_jump(code: int, k: int, jt: int, jf: int) -> bytes:
    return struct.pack("HBBI", code, jt, jf, k)


def _assemble_filter(table: dict[str, object]) -> bytes:
    prog: list[bytes] = []
    prog.append(_bpf_stmt(_BPF_LD_W_ABS, 4))  # load audit arch
    prog.append(_bpf_jump(_BPF_JEQ_K, int(table["audit_arch"]), 1, 0))  # type: ignore[arg-type]
    prog.append(_bpf_stmt(_BPF_RET_K, _RET_KILL))  # foreign arch: kill (fail closed)
    prog.append(_bpf_stmt(_BPF_LD_W_ABS, 0))  # load syscall nr
    for nr in table["denied"]:  # type: ignore[union-attr]
        prog.append(_bpf_jump(_BPF_JEQ_K, int(nr), 0, 1))
        prog.append(_bpf_stmt(_BPF_RET_K, _RET_EPERM))
    for nr, flags_arg_index in table["open_flag_checks"]:  # type: ignore[union-attr]
        # if nr matches: load the flags argument's low word, test the
        # write-capable mask, deny on any hit, then reload the syscall nr.
        prog.append(_bpf_jump(_BPF_JEQ_K, int(nr), 0, 4))
        prog.append(_bpf_stmt(_BPF_LD_W_ABS, 16 + 8 * int(flags_arg_index)))
        prog.append(_bpf_jump(_BPF_JSET_K, _WRITE_OPEN_FLAGS, 0, 1))
        prog.append(_bpf_stmt(_BPF_RET_K, _RET_EPERM))
        prog.append(_bpf_stmt(_BPF_LD_W_ABS, 0))
    prog.append(_bpf_stmt(_BPF_RET_K, _RET_ALLOW))
    return b"".join(prog)


class _SockFprog(ctypes.Structure):
    _fields_ = (("len", ctypes.c_ushort), ("filter", ctypes.c_void_p))


def _libc() -> ctypes.CDLL:
    name = ctypes.util.find_library("c")
    if name is None:
        raise ConfinementError("libc not found; cannot confine (fail closed)")
    return ctypes.CDLL(name, use_errno=True)


def _attempt_network_namespace(libc: ctypes.CDLL) -> bool:
    """Best-effort extra layer: unshare into an empty network namespace."""
    clone_newnet = 0x40000000
    clone_newuser = 0x10000000
    if libc.unshare(clone_newnet) == 0:
        return True
    return libc.unshare(clone_newuser | clone_newnet) == 0


def _install_seccomp_filter(libc: ctypes.CDLL) -> None:
    machine = platform.machine()
    table = _ARCH_TABLES.get(machine)
    if table is None:
        raise ConfinementError(
            f"no seccomp syscall table for architecture {machine!r}; "
            f"containment cannot be established (fail closed)"
        )
    raw_filter = _assemble_filter(table)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise ConfinementError(
            f"PR_SET_NO_NEW_PRIVS failed (errno {ctypes.get_errno()}); "
            f"containment cannot be established (fail closed)"
        )
    buffer = ctypes.create_string_buffer(raw_filter, len(raw_filter))
    prog = _SockFprog(len(raw_filter) // 8, ctypes.cast(buffer, ctypes.c_void_p))
    if libc.prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.byref(prog), 0, 0) != 0:
        raise ConfinementError(
            f"seccomp filter installation failed (errno {ctypes.get_errno()}); "
            f"containment cannot be established (fail closed)"
        )


def confine_this_process() -> tuple[str, ...]:
    """Apply Linux OS-level confinement to the current process.

    Returns the established layers. The seccomp filter is mandatory — it is
    what makes no-egress, no-exec, and no-write hold even against buggy
    code. The network namespace is an additional layer where permitted.
    Raises :class:`ConfinementError` when the mandatory layer cannot be
    established.
    """
    if sys.platform != "linux":
        raise ConfinementError(
            f"self-confinement is Linux-only (platform {sys.platform!r}); "
            f"on macOS the parent must wrap this process in sandbox-exec"
        )
    libc = _libc()
    layers: list[str] = []
    if _attempt_network_namespace(libc):
        layers.append("network-namespace")
    _install_seccomp_filter(libc)
    layers.append("seccomp-filter")
    return tuple(layers)


# ---------------------------------------------------------------------------
# Containment proof probes (platform-neutral; run before any target read)
# ---------------------------------------------------------------------------

_CONTAINED_NETWORK_ERRNOS = frozenset(
    {
        errno.EPERM,
        errno.EACCES,
        errno.ENETUNREACH,
        errno.EADDRNOTAVAIL,
        errno.EAFNOSUPPORT,
        errno.EHOSTUNREACH,
    }
)


def _probe_network_denied() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        if exc.errno in _CONTAINED_NETWORK_ERRNOS:
            return "socket-denied"
        raise ConfinementError(
            f"socket probe failed ambiguously (errno {exc.errno}); containment unproven"
        ) from exc
    try:
        sock.settimeout(0.25)
        try:
            sock.connect(("127.0.0.1", 9))
        except OSError as exc:
            if exc.errno in _CONTAINED_NETWORK_ERRNOS:
                return "connect-denied"
            raise ConfinementError(
                "the network stack is reachable from the inspection process; "
                "containment unproven (a refused connection is not a denial)"
            ) from exc
        raise ConfinementError(
            "an outbound connection succeeded from the inspection process; "
            "containment unproven"
        )
    finally:
        sock.close()


def _probe_file_writes_denied() -> str:
    try:
        fd = os.open("/dev/null", os.O_WRONLY)
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES, errno.EROFS):
            return "write-open-denied"
        raise ConfinementError(
            f"write probe failed ambiguously (errno {exc.errno}); containment unproven"
        ) from exc
    os.close(fd)
    raise ConfinementError(
        "a write-capable open succeeded from the inspection process; containment unproven"
    )


def _probe_process_exec_denied() -> str:
    try:
        pid = os.posix_spawn("/bin/sh", ["/bin/sh", "-c", ":"], {})
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            return "exec-denied"
        raise ConfinementError(
            f"exec probe failed ambiguously (errno {exc.errno}); containment unproven"
        ) from exc
    os.waitpid(pid, 0)
    raise ConfinementError(
        "a shell was spawnable from the inspection process; containment unproven"
    )


def prove_containment() -> tuple[str, ...]:
    """Prove no-network, no-write, no-exec by direct probes, or raise.

    Runs after confinement and before any target read. The probes are
    side-effect-free under containment; if any capability turns out to be
    available, collection never starts.
    """
    return (
        _probe_network_denied(),
        _probe_file_writes_denied(),
        _probe_process_exec_denied(),
    )


# ---------------------------------------------------------------------------
# Child entry point
# ---------------------------------------------------------------------------


def _parse_request(raw: str) -> dict[str, object]:
    request = json.loads(raw)
    if not isinstance(request, dict) or request.get("schema") != REQUEST_SCHEMA:
        raise ValueError(f"request schema must be {REQUEST_SCHEMA!r}")
    unknown = set(request) - {"schema", "approved_roots", "bounds"}
    if unknown:
        raise ValueError(f"unknown request keys {sorted(unknown)}; refusing (fail closed)")
    roots = request.get("approved_roots")
    if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots) or not roots:
        raise ValueError("approved_roots must be a non-empty list of strings")
    return request


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments not in (["--containment", "self"], ["--containment", "external"]):
        print(
            "usage: python -m capability_exchange.adapters.claude_code.contained "
            "--containment {self|external}",
            file=sys.stderr,
        )
        return EXIT_COLLECTION_FAILED

    # Imports and request parsing happen before confinement (imports open
    # files; the filter would also tolerate read-only imports, but nothing
    # here reads the target yet either way).
    try:
        request = _parse_request(sys.stdin.read())
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"invalid collection request: {exc}", file=sys.stderr)
        return EXIT_COLLECTION_FAILED

    from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
    from capability_exchange.adapters.claude_code.collector import EvidenceCollector
    from capability_exchange.adapters.claude_code.contract import claude_code_contract
    from capability_exchange.adapters.claude_code.snapshot import (
        CollectionBounds,
        take_snapshot,
    )

    layers: list[str] = []
    proofs: tuple[str, ...] = ()
    try:
        if arguments[1] == "self":
            layers.extend(confine_this_process())
        else:
            layers.append("external-sandbox-profile")
        proofs = prove_containment()
    except ConfinementError as exc:
        print(f"containment unavailable: {exc}", file=sys.stderr)
        return EXIT_CONTAINMENT_UNAVAILABLE

    try:
        roots = [str(root) for root in request["approved_roots"]]  # type: ignore[index]
        bounds_payload = request.get("bounds") or {}
        bounds = CollectionBounds(**bounds_payload)  # type: ignore[arg-type]
        contract = claude_code_contract(roots)
        allowlist = CanonicalAllowlist(
            contract.read_scope, denied_paths=contract.denied_paths
        )
        snapshot = take_snapshot(allowlist, bounds=bounds)
        envelope = EvidenceCollector(contract, snapshot).collect()
    except Exception as exc:  # noqa: BLE001 - honest abort, partials discarded
        print(
            f"collection aborted ({type(exc).__name__}); partial collection "
            f"discarded with this process",
            file=sys.stderr,
        )
        return EXIT_COLLECTION_FAILED

    print(
        json.dumps(
            {
                "schema": RESULT_SCHEMA,
                "layers": layers,
                "proofs": list(proofs),
                "envelope": envelope.model_dump(mode="json"),
            }
        )
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
