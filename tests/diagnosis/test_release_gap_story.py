"""The release-gap story leads the map and the report (10x item 6).

Design: docs/superpowers/plans/2026-09-07-dex-lens-10x-experience.md, item 6.
Per the completion goal every guarantee here was observed failing on the tree
without the change: map rows carried no release delta (the distance was
computed only inside ``compare()`` and never surfaced), a run with no release
observation rendered *nothing* about the distance (the exact silence the first
real run shipped), and no re-derivation guarded a stored delta.

The signed family contract ships in the next Dex release, so both branches are
proved with invented fixtures: the loud Unknown branch on a family-free
catalogue (it must land regardless of signing), and the Verified-gap branch
through the real signature verifier over test-key-signed family-carrying
envelopes.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.diagnosis.test_family_contract_activation import (
    _catalogue_payload,
    _signed_raw,
    _store_with,
    _test_keyring,
)
from tests.diagnosis.test_family_ledger_report import _report, _VerifiedStore
from tests.diagnosis.test_orchestrator import _replace_stored_artifact
from tests.diagnosis.test_real_comparer_guided_run import RealComparerHarness
from tests.diagnosis.test_significant_family_assessment import (
    _catalogue,
    _family,
    _fingerprint,
    _observation,
)

from capability_exchange.diagnosis.defaults import (
    CachedCatalogueLoader,
    UnknownUntilProposedComparer,
)
from capability_exchange.diagnosis.expectations import (
    NOT_GATED_REASON,
    WOW_EXPECTATIONS,
)
from capability_exchange.diagnosis.observations import ObservationKind, SafeAttribute
from capability_exchange.diagnosis.orchestrator import PrepareDiagnosisRequest
from capability_exchange.diagnosis.report import canonical_ledger_payload
from capability_exchange.diagnosis.run import DiagnosisStage, DiagnosisStateError
from capability_exchange.diagnosis.work import AnalysisMode
from capability_exchange.reports.ledger import load_and_validate_ledger

#: The one manifest family the gap fixture concentrates in: its member skill
#: gains a since_release inside the compared interval; every other family's
#: member predates the inspected release.
GAP_FAMILY_ID = WOW_EXPECTATIONS[0]
SIGNED_OUTCOME = "A synthetic outcome used only to test deterministic matching."


def _manifest_families(gap_member: str = "workflow-skill") -> list[dict[str, object]]:
    families: list[dict[str, object]] = []
    for family_id in WOW_EXPECTATIONS:
        member = gap_member if family_id == GAP_FAMILY_ID else "dormant-helper"
        families.append(
            _family(
                family_id,
                profile="filesystem",
                members=[member],
                components=[{"component_type": "capability", "capability_id": member}],
            )
        )
    return families


def _gap_catalogue():
    """All fourteen manifest families signed; the gap sits in exactly one.

    ``workflow-skill`` (the gap family's only member) carries
    ``since_release`` 1.90.0 — inside the compared interval — while every
    other family's member keeps 1.0.0, so a Verified v1.80.0 install against
    the v1.97.6 catalogue is behind in exactly one signed area.
    """

    payload = _catalogue(*_manifest_families()).model_dump(mode="json")
    workflow = next(
        item for item in payload["capabilities"] if item["capability_id"] == "workflow-skill"
    )
    workflow["since_release"] = "1.90.0"
    return type(_catalogue()).model_validate(payload)


def _release_observation(release_id: str = "v1.80.0"):
    return _observation(ObservationKind.RELEASE, "dex-core").model_copy(
        update={"attributes": (SafeAttribute(key="release-id", value=release_id),)}
    )


def _verified_older_fingerprint():
    return _fingerprint(
        _observation(ObservationKind.SKILL, "workflow-skill"),
        _release_observation(),
    )


def _slice_for(store: _VerifiedStore, seed: str):
    return CachedCatalogueLoader(store).load(
        run_id="run:" + seed * 16,
        fingerprint_digest="sha256:" + seed * 64,
    )


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def test_map_rows_carry_release_deltas_for_verified_older_lineage() -> None:
    """A Verified older lineage against signed families puts the delta on the map.

    Observed failing on the unchanged tree: ``FamilyMap`` had no release
    fields and ``build_family_map`` never looked at release observations —
    the distance existed only inside ``compare()``.
    """

    store = _VerifiedStore(_gap_catalogue(), core_release="v1.97.6")
    family_map = UnknownUntilProposedComparer(store).family_map(
        fingerprint=_verified_older_fingerprint(),
        catalogue=_slice_for(store, "1"),
    )

    assert family_map.inspected_release == "v1.80.0"
    assert family_map.current_release == "v1.97.6"
    assert family_map.release_evidence_references

    rows_by_id = {row.family_id: row for row in family_map.rows}
    gap_row = rows_by_id[GAP_FAMILY_ID]
    assert gap_row.release_delta is not None
    assert gap_row.release_delta.newer_member_ids == ("workflow-skill",)
    assert gap_row.release_delta.changed_member_ids == ()
    # The educational voice quotes only the signed outcome — never invention.
    assert gap_row.release_delta.outcome == SIGNED_OUTCOME
    assert all(
        rows_by_id[family_id].release_delta is None
        for family_id in WOW_EXPECTATIONS
        if family_id != GAP_FAMILY_ID
    )


def test_release_gap_headline_leads_the_report() -> None:
    """The rendered report says plainly how far behind, naming the right family.

    Observed failing on the unchanged tree: the version distance was rendered
    only in the what-changed section, with no headline near the coverage
    block and no honest release count anywhere.
    """

    store = _VerifiedStore(_gap_catalogue(), core_release="v1.97.6")
    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=_verified_older_fingerprint(),
        catalogue=_slice_for(store, "2"),
        jobs=(),
        proposals=(),
    )

    assert ledger.version_distance is not None
    # The honest lower bound: the signed catalogue names 1.90.0 and its own
    # v1.97.6 as releases newer than the inspected v1.80.0 — nothing more.
    assert ledger.version_distance.newer_release_ids == ("1.90.0", "v1.97.6")

    rendered = _report(ledger)
    assert "## Where your install stands" in rendered
    assert "Your install identifies Dex Core v1.80.0" in rendered
    assert "at least 2 releases behind" in rendered
    assert "The gap concentrates in 1 signed capability area:" in rendered
    assert f"(`{GAP_FAMILY_ID}`): 1 signed capability newer than your release" in rendered
    # Each named family points at its map row, and benefits are quoted only
    # from signed outcomes elsewhere — the headline itself stays counts+titles.
    assert "row in the deterministic family map" in rendered
    # The headline leads: after the coverage block, before the detail section.
    assert (
        rendered.index("## How much was examined")
        < rendered.index("## Where your install stands")
        < rendered.index("## What has changed since your identified Dex release")
    )


def test_missing_release_observation_is_a_loud_priced_unknown() -> None:
    """No release observation → the same slot says Unknown and what fixes it.

    Observed failing on the unchanged tree: with ``version_distance`` None the
    report said nothing at all about the distance — the exact silence the
    first real run shipped.
    """

    store = _VerifiedStore(_gap_catalogue(), core_release="v1.97.6")
    fingerprint = _fingerprint(_observation(ObservationKind.SKILL, "workflow-skill"))

    family_map = UnknownUntilProposedComparer(store).family_map(
        fingerprint=fingerprint,
        catalogue=_slice_for(store, "3"),
    )
    assert family_map.inspected_release is None
    assert family_map.release_evidence_references == ()
    assert all(row.release_delta is None for row in family_map.rows)

    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=_slice_for(store, "4"),
        jobs=(),
        proposals=(),
    )
    rendered = _report(ledger)
    assert "## Where your install stands" in rendered
    assert (
        "How far this install stands behind the current Dex release is Unknown: "
        "the approved snapshot carries no Dex Core release observation."
    ) in rendered
    # Priced, with the one establishing observation named in plain words.
    assert "`.dex-version` file or a `CHANGELOG.md`" in rendered
    assert "approve the folder that holds it and run again" in rendered


def test_family_free_catalogue_keeps_not_gated_rows_and_claims_no_gap() -> None:
    """Without the signed contract no delta may be invented, loudly said.

    Observed failing on the unchanged tree: nothing rendered in the slot, so
    the explicit no-claim sentence was absent.
    """

    store = _VerifiedStore(_catalogue(), core_release="v1.97.6")
    fingerprint = _fingerprint(
        _observation(ObservationKind.MCP_SERVER, "work-mcp"),
        _release_observation(),
    )

    family_map = UnknownUntilProposedComparer(store).family_map(
        fingerprint=fingerprint,
        catalogue=_slice_for(store, "5"),
    )
    # The not-gated rows stand untouched; no row carries an invented delta.
    assert all(row.state.value == "not-gated" for row in family_map.rows)
    assert all(row.reason == NOT_GATED_REASON for row in family_map.rows)
    assert all(row.release_delta is None for row in family_map.rows)
    # The lineage facts stay honest facts — established, but not a gap claim.
    assert family_map.inspected_release == "v1.80.0"

    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=_slice_for(store, "6"),
        jobs=(),
        proposals=(),
    )
    assert ledger.version_distance is None
    rendered = _report(ledger)
    assert "## Where your install stands" in rendered
    assert "signs no capability-family contract" in rendered
    assert "Nothing here claims your install is behind or current." in rendered
    assert "releases behind" not in rendered
    assert "at least" not in rendered.split("## Where your install stands")[1].split("##")[0]


def test_unknown_branch_lands_without_the_family_contract() -> None:
    """The loud Unknown ships now — it never waits for the contract signing."""

    store = _VerifiedStore(_catalogue(), core_release="v1.97.6")
    fingerprint = _fingerprint(_observation(ObservationKind.MCP_SERVER, "work-mcp"))

    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=_slice_for(store, "7"),
        jobs=(),
        proposals=(),
    )
    rendered = _report(ledger)
    assert (
        "How far this install stands behind the current Dex release is Unknown"
    ) in rendered
    assert "carries no Dex Core release observation" in rendered


def test_map_derivation_is_deterministic_and_delta_bearing() -> None:
    """Two derivations over the same inputs are byte-identical, deltas included."""

    store = _VerifiedStore(_gap_catalogue(), core_release="v1.97.6")
    comparer = UnknownUntilProposedComparer(store)
    catalogue_slice = _slice_for(store, "8")

    first = comparer.family_map(
        fingerprint=_verified_older_fingerprint(), catalogue=catalogue_slice
    )
    second = comparer.family_map(
        fingerprint=_verified_older_fingerprint(), catalogue=catalogue_slice
    )

    assert any(row.release_delta is not None for row in first.rows)
    assert first == second
    assert _canonical(first.model_dump(mode="json")) == _canonical(
        second.model_dump(mode="json")
    )


def test_forged_stored_map_delta_is_ignored_and_compare_refuses(tmp_path: Path) -> None:
    """A tampered stored delta never reaches a reader; comparison fails closed.

    Mirrors RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT for the release-gap fields:
    the stored family-map artifact is an audit record, so stripping the gap
    from it must change nothing a reader sees, and comparison must refuse the
    disagreeing run instead of closing over it.  Observed failing on the
    unchanged tree at the first assertion: no stored or derived row carried a
    release delta at all.
    """

    catalogue = _gap_catalogue()
    harness = RealComparerHarness(
        tmp_path, catalogue=catalogue, fingerprint=_verified_older_fingerprint()
    )
    # The shared store gains the release endpoint the gap derivation needs.
    harness.store.load_last_verified = lambda **_kwargs: SimpleNamespace(
        catalogue=catalogue,
        metadata=SimpleNamespace(catalog_version=7, core_release="v1.97.6"),
        _signed_json="invented-signed-catalogue",
    )
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(
            roots=(harness.root,), analysis_mode=AnalysisMode.INVENTORY_ONLY
        )
    )
    run_id = prepared.run_id
    harness.run_to(run_id, DiagnosisStage.JOBS_CONFIRMED)

    derived = harness.engine.family_map(run_id)
    gap_rows = [row for row in derived.rows if row.release_delta is not None]
    assert gap_rows, "the fixture must derive at least one release delta"

    forged = derived.model_dump(mode="json")
    for row in forged["rows"]:
        row["release_delta"] = None
    forged["inspected_release"] = None
    forged["release_evidence_references"] = []
    _replace_stored_artifact(harness, run_id, "family-map", forged)

    # Every read surface re-derives: the stripped gap never reaches a reader.
    reread = harness.engine.family_map(run_id)
    assert any(row.release_delta is not None for row in reread.rows)
    assert reread.inspected_release == "v1.80.0"

    # And comparison refuses the run whose stored audit record disagrees.
    with pytest.raises(DiagnosisStateError, match="family map"):
        harness.engine.advance(run_id)


def test_tampered_ledger_release_count_is_refused_on_reload(tmp_path: Path) -> None:
    """The stored ledger's release count is re-derived from signed lineage.

    Observed failing with the re-derivation check absent: an inflated
    ``newer_release_ids`` reloaded cleanly, so a tampered saved ledger could
    headline any number of releases behind.
    """

    store = _VerifiedStore(_gap_catalogue(), core_release="v1.97.6")
    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=_verified_older_fingerprint(),
        catalogue=_slice_for(store, "9"),
        jobs=(),
        proposals=(),
    )
    stored = canonical_ledger_payload(ledger)
    assert stored["version_distance"] is not None
    stored["version_distance"]["newer_release_ids"] = [
        "1.90.0",
        "1.91.0",
        "1.92.0",
        "v1.97.6",
    ]
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(stored), encoding="utf-8")

    loaded, problems = load_and_validate_ledger(path, store.envelope)

    assert loaded is None
    assert any("newer releases" in problem for problem in problems)


def test_signed_family_contract_activates_map_release_deltas(tmp_path: Path) -> None:
    """The Verified-gap branch works end to end over a test-key-signed envelope.

    The real verifier, the real store cache, the real loader and comparer —
    no stand-in catalogue objects — prove the branch is ready the moment the
    production contract is signed.
    """

    payload = _catalogue_payload(*_manifest_families())
    for item in payload["capabilities"]:
        if item["capability_id"] == "workflow-skill":
            item["since_release"] = "1.90.0"
    store = _store_with(
        _signed_raw(payload), tmp_path / "catalogue", keyring=_test_keyring()
    )
    keyring = _test_keyring()

    catalogue_slice = CachedCatalogueLoader(store, keyring=keyring).load(
        run_id="run:" + "a" * 16,
        fingerprint_digest="sha256:" + "b" * 64,
    )
    family_map = UnknownUntilProposedComparer(store, keyring=keyring).family_map(
        fingerprint=_verified_older_fingerprint(),
        catalogue=catalogue_slice,
    )

    # The signed envelope's metadata names core_release v1.98.0.
    assert family_map.current_release == "v1.98.0"
    assert family_map.inspected_release == "v1.80.0"
    gap_row = next(row for row in family_map.rows if row.family_id == GAP_FAMILY_ID)
    assert gap_row.release_delta is not None
    assert gap_row.release_delta.newer_member_ids == ("workflow-skill",)
    assert gap_row.release_delta.outcome == SIGNED_OUTCOME


def test_signed_family_free_catalogue_never_invents_a_delta(tmp_path: Path) -> None:
    """The same lineage against a genuinely signed family-free catalogue: no gap."""

    store = _store_with(
        _signed_raw(_catalogue_payload()), tmp_path / "catalogue", keyring=_test_keyring()
    )
    keyring = _test_keyring()

    catalogue_slice = CachedCatalogueLoader(store, keyring=keyring).load(
        run_id="run:" + "c" * 16,
        fingerprint_digest="sha256:" + "d" * 64,
    )
    family_map = UnknownUntilProposedComparer(store, keyring=keyring).family_map(
        fingerprint=_verified_older_fingerprint(),
        catalogue=catalogue_slice,
    )

    assert all(row.release_delta is None for row in family_map.rows)
    assert all(row.state.value == "not-gated" for row in family_map.rows)
