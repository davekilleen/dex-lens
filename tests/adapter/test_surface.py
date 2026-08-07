"""The diagnosis surface exposes read, preview, and bounded-status ONLY.

Non-negotiable boundary 1 (HANDOFF 3.5): no mutating entry point exists on
the diagnosis side. This is asserted structurally — a scan over every public
callable in the adapter package — and the scan itself runs at package import.
"""

import inspect
import types
from datetime import UTC, datetime

import pytest

import capability_exchange.adapter
from capability_exchange.adapter.envelope import (
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.adapter.surface import (
    MUTATING_NAME_TOKENS,
    PREVIEW_LIMIT_MAX,
    DiagnosisSurface,
    PreviewBoundError,
    ProbeNotFoundError,
    ReadOnlySurfaceViolation,
    assert_read_only_surface,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

CAPTURED = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@pytest.fixture()
def surface() -> DiagnosisSurface:
    evidence = tuple(
        EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=CAPTURED,
            reference=f"probe:skills-present:{index}",
        )
        for index in range(5)
    )
    env = AdapterResultEnvelope(
        adapter_id="claude-code-macos",
        contract_version="1.0.0",
        collected_at=CAPTURED,
        probes=(
            ProbeResult(
                probe_id="skills-present",
                health=InstrumentHealth.HEALTHY,
                evidence=evidence,
            ),
            ProbeResult(
                probe_id="hooks-configured",
                health=InstrumentHealth.INTENTIONALLY_OFF,
                detail="hooks disabled in the person's own settings",
            ),
            ProbeResult(
                probe_id="memory-files",
                health=InstrumentHealth.BROKEN,
                detail="probe crashed before reading",
            ),
        ),
    )
    return DiagnosisSurface(env)


class TestReadPreviewStatus:
    def test_read_envelope_returns_the_envelope(self, surface: DiagnosisSurface) -> None:
        assert surface.read_envelope().adapter_id == "claude-code-macos"

    def test_read_probe(self, surface: DiagnosisSurface) -> None:
        assert surface.read_probe("memory-files").health is InstrumentHealth.BROKEN

    def test_unknown_probe_refused_honestly(self, surface: DiagnosisSurface) -> None:
        with pytest.raises(ProbeNotFoundError, match="no-such-probe"):
            surface.read_probe("no-such-probe")

    def test_preview_is_bounded(self, surface: DiagnosisSurface) -> None:
        assert len(surface.preview_evidence("skills-present", limit=2)) == 2

    def test_preview_default_limit(self, surface: DiagnosisSurface) -> None:
        assert len(surface.preview_evidence("skills-present")) == 5

    def test_preview_refuses_out_of_bound_limits(self, surface: DiagnosisSurface) -> None:
        with pytest.raises(PreviewBoundError):
            surface.preview_evidence("skills-present", limit=0)
        with pytest.raises(PreviewBoundError):
            surface.preview_evidence("skills-present", limit=PREVIEW_LIMIT_MAX + 1)

    def test_status_is_counts_only(self, surface: DiagnosisSurface) -> None:
        status = surface.status()
        assert status == {
            "probes": 3,
            "healthy": 1,
            "intentionally-off": 1,
            "broken": 1,
            "could-not-check": 0,
        }
        assert all(isinstance(value, int) for value in status.values())

    def test_surface_offers_read_preview_status_and_nothing_else(self) -> None:
        public = {
            name
            for name, member in inspect.getmembers(DiagnosisSurface)
            if not name.startswith("_") and callable(member)
        }
        assert public == {"read_envelope", "read_probe", "preview_evidence", "status"}


def _fake_module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(f"capability_exchange.adapter.{name}")
    for attr_name, attr in attrs.items():
        if hasattr(attr, "__module__"):
            try:
                attr.__module__ = module.__name__
            except (AttributeError, TypeError):
                pass
        setattr(module, attr_name, attr)
    return module


class TestStructuralReadOnlyAssertion:
    def test_adapter_package_has_no_mutating_entry_point(self) -> None:
        # The non-negotiable boundary itself: the scan passes on the real
        # package.
        assert_read_only_surface()

    def test_assertion_runs_at_package_import(self) -> None:
        source = inspect.getsource(capability_exchange.adapter)
        assert "assert_read_only_surface()" in source

    def test_package_exports_no_mutating_callable_name(self) -> None:
        # Entry points are callables; data constants (like the denylist
        # itself, whose name necessarily contains "mutating") are not.
        for name in capability_exchange.adapter.__all__:
            if not callable(getattr(capability_exchange.adapter, name)):
                continue
            tokens = {token.lower() for token in name.replace("_", " ").split()}
            assert not tokens & MUTATING_NAME_TOKENS, name

    def test_scanner_catches_a_mutating_function(self) -> None:
        def write_config() -> None:  # pragma: no cover - never called
            raise AssertionError

        fake = _fake_module("fake_writer", write_config=write_config)
        with pytest.raises(ReadOnlySurfaceViolation, match="write_config"):
            assert_read_only_surface(modules=[fake])

    def test_scanner_catches_a_mutating_method(self) -> None:
        class HostEditor:
            def apply_change(self) -> None:  # pragma: no cover - never called
                raise AssertionError

        fake = _fake_module("fake_editor", HostEditor=HostEditor)
        with pytest.raises(ReadOnlySurfaceViolation, match="apply_change"):
            assert_read_only_surface(modules=[fake])

    def test_scanner_catches_a_camel_case_mutating_class(self) -> None:
        class DeleteRequest:  # pragma: no cover - never instantiated
            pass

        fake = _fake_module("fake_deleter", DeleteRequest=DeleteRequest)
        with pytest.raises(ReadOnlySurfaceViolation, match="DeleteRequest"):
            assert_read_only_surface(modules=[fake])

    def test_scanner_catches_a_mutating_property(self) -> None:
        class Sneaky:
            @property
            def send_target(self) -> str:  # pragma: no cover - never read
                return ""

        fake = _fake_module("fake_sender", Sneaky=Sneaky)
        with pytest.raises(ReadOnlySurfaceViolation, match="send_target"):
            assert_read_only_surface(modules=[fake])

    def test_scanner_ignores_foreign_reexports(self) -> None:
        # Objects merely imported from outside the adapter package are not
        # its entry points; the boundary scan targets what the package
        # itself defines.
        fake = _fake_module("fake_imports")
        fake.hexlify = __import__("binascii").hexlify
        assert_read_only_surface(modules=[fake])
