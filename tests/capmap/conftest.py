"""Shared builders for the M-D Capability Map tests.

Everything is built through the real collector path where possible
(``assess`` over conftest envelopes), so the renderer/correction tests
exercise the same Finding objects the product produces.
"""

from __future__ import annotations

import pytest
from tests.diagnosis.conftest import (
    COLLECTED_AT,
    contract,
    envelope,
    item,
    observed_probe,
    presence_only_envelope,
    probe,
)

from capability_exchange.adapter import InstrumentHealth
from capability_exchange.capmap import CapabilityMap
from capability_exchange.diagnosis import assess

__all__ = [
    "COLLECTED_AT",
    "contract",
    "envelope",
    "item",
    "observed_probe",
    "presence_only_envelope",
    "probe",
]


def one_job_map(job_id: str = "weekly-report") -> CapabilityMap:
    """A map for one confirmed job over the M1 presence-only envelope."""
    return assess([contract(job_id)], presence_only_envelope())


def two_job_map() -> CapabilityMap:
    return assess(
        [contract("alpha-job"), contract("beta-job")], presence_only_envelope()
    )


def unknown_heavy_map() -> CapabilityMap:
    """A map where instruments failed: could-not-check and broken probes.

    Produces findings with blocked/unverified evidence and honest Unknowns —
    the fixture for honest-unknown rendering.
    """
    return assess(
        [contract()],
        envelope(
            probe(
                "skills-present",
                health=InstrumentHealth.COULD_NOT_CHECK,
                detail="the approved scope did not include the skills directory",
            ),
            probe(
                "instructions-present",
                health=InstrumentHealth.BROKEN,
                detail="the instrument failed while reading",
            ),
        ),
    )


@pytest.fixture
def capability_map() -> CapabilityMap:
    return one_job_map()
