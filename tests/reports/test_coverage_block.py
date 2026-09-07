"""The headline coverage block: not-assessed is loud, placed, and offered a follow-up.

The first real run assessed 21 of 115 catalogue entries and the 94 left
``not-assessed`` hid in the appendix; the person concluded the product had
missed a tonne of capability — correctly. These tests hold the guarantees
that prevent a recurrence: the rendered report says near the top how many
signed entries were examined and where the rest sit, and ``reports check``
refuses a report whose ledger carries unexamined entries but whose markdown
lost that block.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import NOW as CATALOGUE_NOW
from tests.catalogue.test_v2_verifier import sign_envelope, unsigned_envelope
from tests.diagnosis.test_run import NOW, RUN_ID
from tests.reports.test_ledger import _full_ledger, _grounded_report

from capability_exchange.catalogue.v2 import (
    KeyRing,
    VerifiedCatalogueStore,
    verify_catalogue_envelope,
)
from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
)
from capability_exchange.diagnosis.families import FamilyAvailability
from capability_exchange.diagnosis.report import (
    ReportModel,
    canonical_coverage_block,
    canonical_ledger_digest,
    canonical_ledger_payload,
    coverage_block_errors,
)
from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    INPUT_SCHEMA_VERSION,
    RunIdentity,
)
from capability_exchange.diagnosis.significant_families import (
    FamilyAssessmentDisposition,
)
from capability_exchange.reports import cli

TOTAL = 115
ASSESSED = 21


def _entry_id(index: int) -> str:
    return f"invented-capability-{index:03d}"


def _entries(assessed: int, total: int) -> tuple[CatalogueDisposition, ...]:
    return tuple(
        CatalogueDisposition(
            catalogue_id=_entry_id(index),
            capability_id="unassigned",
            disposition=(
                Disposition.NOT_RELEVANT if index < assessed else Disposition.NOT_ASSESSED
            ),
            reason=(
                "Not relevant to the invented setup."
                if index < assessed
                else "Not assessed in this run."
            ),
        )
        for index in range(total)
    )


def _family(family_id: str, title: str, member_ids: tuple[str, ...]) -> dict[str, object]:
    return {
        "family_id": family_id,
        "title": title,
        "outcome": f"{title} outcome, described by the signed catalogue.",
        "signed_availability": FamilyAvailability.AVAILABLE.value,
        "available_member_ids": list(member_ids),
        "unavailable_member_ids": [],
        "recommendable_member_ids": list(member_ids),
        "matched_components": [],
        "matched_observation_ids": [],
        "unresolved_components": [],
        "evidence_references": [],
        "disposition": FamilyAssessmentDisposition.NOT_ASSESSED.value,
        "reason": "Not assessed yet.",
    }


#: Three signed areas: one wholly unexamined, one partly, one fully assessed.
_FAMILIES = (
    _family(
        "meeting-follow-through",
        "Meeting follow-through",
        tuple(_entry_id(index) for index in range(21, 27)),
    ),
    _family(
        "memory",
        "Memory",
        (_entry_id(6), _entry_id(27), _entry_id(28)),
    ),
    _family(
        "backup-safety",
        "Backup safety",
        tuple(_entry_id(index) for index in range(6)),
    ),
)


def _ledger(
    *,
    assessed: int = ASSESSED,
    total: int = TOTAL,
    families: tuple[dict[str, object], ...] = _FAMILIES,
) -> ComparisonLedger:
    return ComparisonLedger.model_validate(
        {
            "catalogue_version": 1,
            "catalogue_sha256": "a" * 64,
            "capabilities": [],
            "entries": [entry.model_dump(mode="json") for entry in _entries(assessed, total)],
            "family_entries": list(families),
            "reciprocal_answer": "No transferable method cleared the evidence bar.",
        }
    )


def _report(ledger: ComparisonLedger) -> ReportModel:
    return ReportModel.from_result(
        run_identity=RunIdentity(
            run_id=RUN_ID,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            created_at=NOW,
        ),
        ledger=ledger,
        ledger_sha256=canonical_ledger_digest(ledger),
    )


class TestTheCoverageBlockIsLoudAndPlaced:
    def test_the_block_names_the_counts_with_their_denominator(self) -> None:
        block = canonical_coverage_block(_ledger())

        assert block.startswith("## How much was examined\n")
        assert (
            "Of the 115 entries in the signed Dex catalogue, 21 were assessed "
            "against your system and 94 were not examined at all." in block
        )

    def test_the_unexamined_concentrate_in_named_signed_areas(self) -> None:
        block = canonical_coverage_block(_ledger())

        meeting = (
            "- Meeting follow-through (`meeting-follow-through`): "
            "6 of its 6 signed members were not examined."
        )
        memory = "- Memory (`memory`): 2 of its 3 signed members were not examined."
        assert meeting in block
        assert memory in block
        # The wholly assessed area is not blamed, and the fuller gap leads.
        assert "Backup safety" not in block
        assert block.index(meeting) < block.index(memory)

    def test_unexamined_entries_outside_every_area_are_still_counted(self) -> None:
        block = canonical_coverage_block(_ledger())

        assert "- Outside every signed capability area: " in block
        # 94 not examined; 6 + 2 sit in named areas, so 86 sit outside and
        # the first few are named with the remainder counted, never hidden.
        assert f"`{_entry_id(29)}`" in block
        assert "and 78 more in the ledger appendix." in block

    def test_the_block_offers_the_follow_up_in_one_plain_sentence(self) -> None:
        block = canonical_coverage_block(_ledger())

        assert (
            "A deeper look at these areas is a second, shorter run — it "
            "examines only what you point at." in block
        )

    def test_without_signed_families_the_top_unassessed_ids_are_named(self) -> None:
        block = canonical_coverage_block(_ledger(families=()))

        assert "no signed capability-family contract" in block.lower()
        assert f"`{_entry_id(21)}`" in block
        assert f"`{_entry_id(28)}`" in block
        assert "and 86 more in the ledger appendix." in block

    def test_the_rendered_report_carries_the_block_near_the_top(self) -> None:
        ledger = _ledger()
        markdown = _report(ledger).render_markdown(ledger)

        block = canonical_coverage_block(ledger)
        assert block in markdown
        assert markdown.index(block) < markdown.index("## What is working especially well")
        assert markdown.index(block) < markdown.index("## Coverage and limits")

    def test_a_fully_assessed_ledger_says_so_plainly(self) -> None:
        ledger = _ledger(assessed=TOTAL)
        block = canonical_coverage_block(ledger)

        assert "All 115 entries in the signed Dex catalogue were assessed" in block
        assert "not examined" not in block

    def test_the_block_is_deterministic_under_reordered_input(self) -> None:
        ledger = _ledger()
        reordered = ComparisonLedger.model_validate(
            {
                **canonical_ledger_payload(ledger),
                "entries": [
                    entry.model_dump(mode="json") for entry in reversed(ledger.entries)
                ],
                "family_entries": [
                    dict(family) for family in reversed(_FAMILIES)
                ],
            }
        )

        assert canonical_coverage_block(ledger) == canonical_coverage_block(reordered)


class TestTheCheckRefusesAReportThatLostTheBlock:
    def test_errors_name_the_missing_block_when_not_assessed_is_nonzero(self) -> None:
        ledger = _ledger()
        markdown = _report(ledger).render_markdown(ledger)
        stripped = markdown.replace(canonical_coverage_block(ledger), "")

        assert coverage_block_errors(markdown, ledger) == ()
        errors = coverage_block_errors(stripped, ledger)
        assert len(errors) == 1
        assert "94" in errors[0] and "115" in errors[0]

    def test_a_fully_assessed_ledger_demands_no_block(self) -> None:
        ledger = _ledger(assessed=TOTAL)

        assert coverage_block_errors("# Diagnosis\n", ledger) == ()

    @staticmethod
    def _verified_catalogue_with_unexamined_entries():
        """A signed three-entry catalogue: one entry assessed leaves two behind.

        The shared single-entry fixture catalogue cannot exercise this rule —
        its one entry is assessed, so nothing remains unexamined and the
        coverage block owes nothing.
        """
        signing_key = Ed25519PrivateKey.from_private_bytes(
            b"coverage-block-test-key".ljust(32, b"!")
        )
        public_key = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        keyring = KeyRing({"coverage-test": base64.b64encode(public_key).decode("ascii")})
        envelope = unsigned_envelope(version=6, key_id="coverage-test")
        base_capability = envelope["catalogue"]["capabilities"][0]
        for suffix in ("b", "c"):
            capability = copy.deepcopy(base_capability)
            capability["capability_id"] = f"invented-coverage-{suffix}"
            capability["title"] = f"Invented coverage {suffix.upper()}"
            envelope["catalogue"]["capabilities"].append(capability)
        raw = sign_envelope(envelope, signing_key)
        return verify_catalogue_envelope(raw, keyring=keyring, now=CATALOGUE_NOW), keyring

    @pytest.fixture
    def saved_pair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path, ComparisonLedger]:
        """A saved report and ledger, exactly as a finished diagnosis writes them."""
        verified, keyring = self._verified_catalogue_with_unexamined_entries()
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        from capability_exchange.catalogue.subscription import default_lens_app_storage

        VerifiedCatalogueStore(default_lens_app_storage()).save_verified(verified)
        monkeypatch.setattr(cli, "default_keyring", lambda: keyring)
        ledger = _full_ledger(verified)
        source = tmp_path / "report.md"
        source.write_text(_grounded_report(ledger), encoding="utf-8")
        ledger_path = tmp_path / "ledger.json"
        ledger_path.write_text(
            json.dumps(canonical_ledger_payload(ledger)), encoding="utf-8"
        )
        return source, ledger_path, ledger

    def test_the_untouched_pair_passes(
        self, saved_pair: tuple[Path, Path, ComparisonLedger]
    ) -> None:
        source, ledger_path, _ledger_model = saved_pair

        assert cli.reports_main(["check", str(source), "--ledger", str(ledger_path)]) == 0

    def test_check_refuses_the_report_stripped_of_the_coverage_block(
        self,
        saved_pair: tuple[Path, Path, ComparisonLedger],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, ledger_path, ledger = saved_pair
        block = canonical_coverage_block(ledger)
        markdown = source.read_text(encoding="utf-8")
        assert block in markdown, "the grounded fixture must carry the block it strips"
        source.write_text(markdown.replace(block, ""), encoding="utf-8")

        assert cli.reports_main(["check", str(source), "--ledger", str(ledger_path)]) == 2
        assert "how much was examined" in capsys.readouterr().err.lower()

    def test_save_refuses_the_stripped_report_too(
        self, saved_pair: tuple[Path, Path, ComparisonLedger], tmp_path: Path
    ) -> None:
        source, ledger_path, ledger = saved_pair
        markdown = source.read_text(encoding="utf-8")
        source.write_text(
            markdown.replace(canonical_coverage_block(ledger), ""), encoding="utf-8"
        )

        assert (
            cli.reports_main(
                ["save", str(source), "--ledger", str(ledger_path), "--for", str(tmp_path)]
            )
            == 2
        )
