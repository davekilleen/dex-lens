"""Smoke test: the capability_exchange package imports and declares itself.

Test-first scaffold check for M1. The real gate suites (G1, G2, R2 hostile
fixtures) land with the containment core; this only proves the package
skeleton and tooling are wired.
"""

import capability_exchange


def test_package_imports() -> None:
    assert capability_exchange.__version__


def test_diagnosis_side_declares_read_only() -> None:
    """The diagnosis side must never expose a mutating entry point.

    At scaffold stage this asserts the declared posture; the M1 containment
    core backs it with syscall-level proof (G1) and the conformance suite
    asserts the model-facing surface exposes read/preview/status only.
    """
    assert capability_exchange.DIAGNOSIS_READ_ONLY is True
