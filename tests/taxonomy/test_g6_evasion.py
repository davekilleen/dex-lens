"""G6 taxonomy-evasion hostile fixtures (HANDOFF 5.1; gates.md G6 strategy b).

Job descriptions worded to evade classification must still route to
high-impact: the three canonical evasions named by the gate, further
euphemistic phrasings, multilingual phrasings, and the benign-job /
high-impact-adaptation crossover (the taxonomy half here; the G3 allowlist
independently blocks the operation at M4 — both layers tested separately).

Rule (HANDOFF 5.1): any hostile-fixture failure anywhere re-opens G6.
"""

from __future__ import annotations

import pytest

from capability_exchange.taxonomy.categories import HighImpactCategory
from capability_exchange.taxonomy.classifier import (
    automated_adaptation_allowed,
    classify_job,
    classify_text,
)


class TestCanonicalEvasions:
    """The three evasions gates.md G6 names verbatim."""

    def test_streamline_outbound_correspondence_is_sending_messages(self) -> None:
        result = classify_text("Streamline outbound correspondence")
        assert result.high_impact
        assert HighImpactCategory.SENDING_MESSAGES in result.categories

    def test_tidy_up_old_records_is_deletion(self) -> None:
        result = classify_text("Tidy up old records")
        assert result.high_impact
        assert HighImpactCategory.DELETION in result.categories

    def test_sync_my_access_tokens_is_credentials(self) -> None:
        result = classify_text("Sync my access tokens")
        assert result.high_impact
        assert HighImpactCategory.CREDENTIALS in result.categories


class TestEuphemisticEvasions:
    @pytest.mark.parametrize(
        ("text", "category"),
        [
            ("Keep my contacts warm each week", HighImpactCategory.SENDING_MESSAGES),
            ("Circulate the memo when it's ready", HighImpactCategory.SENDING_MESSAGES),
            ("Ping the team about standup", HighImpactCategory.SENDING_MESSAGES),
            ("Top up whatever the office kitchen needs", HighImpactCategory.MONEY_PURCHASING),
            ("Restock the pantry staples", HighImpactCategory.MONEY_PURCHASING),
            ("Open up the shared folder to the interns", HighImpactCategory.PERMISSIONS),
            ("Lock down the drafts directory", HighImpactCategory.PERMISSIONS),
            ("Declutter my old project folders", HighImpactCategory.DELETION),
            ("Get rid of the stuff we never open", HighImpactCategory.DELETION),
            ("Consolidate my logins into one place", HighImpactCategory.CREDENTIALS),
            ("Refresh my sign-in stuff everywhere", HighImpactCategory.CREDENTIALS),
            ("Keep my wellness routine on track", HighImpactCategory.HEALTH),
            ("Track my meds for the month", HighImpactCategory.HEALTH),
            ("Redline the agreement before Friday", HighImpactCategory.LEGAL),
            ("Get the paperwork for my case in order", HighImpactCategory.LEGAL),
            ("Make my money work harder", HighImpactCategory.FINANCIAL_DECISIONS),
            ("Grow my nest egg quietly", HighImpactCategory.FINANCIAL_DECISIONS),
            (
                "Organize what clients shared with me",
                HighImpactCategory.THIRD_PARTY_CONFIDENTIAL_DATA,
            ),
            (
                "Pull together people's details from the forms",
                HighImpactCategory.THIRD_PARTY_CONFIDENTIAL_DATA,
            ),
        ],
    )
    def test_euphemism_routes_to_high_impact(
        self, text: str, category: HighImpactCategory
    ) -> None:
        result = classify_text(text)
        assert result.high_impact, text
        assert category in result.categories, text
        assert not automated_adaptation_allowed(result)


class TestMultilingualEvasions:
    @pytest.mark.parametrize(
        ("text", "category"),
        [
            # Spanish
            ("Mandar un correo a mi jefe", HighImpactCategory.SENDING_MESSAGES),
            ("Comprar los regalos de fin de año", HighImpactCategory.MONEY_PURCHASING),
            ("Eliminar los archivos viejos", HighImpactCategory.DELETION),
            ("Actualizar la contraseña del banco", HighImpactCategory.CREDENTIALS),
            ("Dar permisos al equipo externo", HighImpactCategory.PERMISSIONS),
            # French
            ("Envoyer un message au client", HighImpactCategory.SENDING_MESSAGES),
            ("Payer la facture du studio", HighImpactCategory.MONEY_PURCHASING),
            ("Supprimer les vieux fichiers", HighImpactCategory.DELETION),
            ("Changer le mot de passe du site", HighImpactCategory.CREDENTIALS),
            ("Comparer les placements possibles", HighImpactCategory.FINANCIAL_DECISIONS),
            # German
            ("Eine Nachricht an den Vermieter senden", HighImpactCategory.SENDING_MESSAGES),
            ("Neues Zubehör für das Studio kaufen", HighImpactCategory.MONEY_PURCHASING),
            ("Alte Dateien löschen", HighImpactCategory.DELETION),
            ("Das Passwort für den Router ändern", HighImpactCategory.CREDENTIALS),
            ("Kundendaten neu sortieren", HighImpactCategory.THIRD_PARTY_CONFIDENTIAL_DATA),
        ],
    )
    def test_non_english_phrasing_routes_to_high_impact(
        self, text: str, category: HighImpactCategory
    ) -> None:
        result = classify_text(text)
        assert result.high_impact, text
        assert category in result.categories, text


class TestBenignJobHighImpactAdaptationCrossover:
    """HANDOFF 5.1: benign-job / high-impact-adaptation crossover.

    The taxonomy half lives here at M2: the job is honestly benign at
    diagnosis, and classification applied to the proposed adaptation's own
    description catches the high-impact operation. The independent G3
    allowlist layer that must also block it lands at M4 and is tested
    separately (gates.md closing note: one surviving layer still blocks).
    """

    BENIGN_JOB = "Keep my reading list organized by topic"
    PROPOSED_ADAPTATION = (
        "Install a routine that emails me the reading list every Friday"
    )

    def test_the_job_itself_is_benign_at_diagnosis(self) -> None:
        assert not classify_job(self.BENIGN_JOB).high_impact

    def test_the_proposed_adaptation_text_is_high_impact(self) -> None:
        result = classify_text(self.PROPOSED_ADAPTATION)
        assert result.high_impact
        assert HighImpactCategory.SENDING_MESSAGES in result.categories
        assert not automated_adaptation_allowed(result)


class TestObfuscationAttempts:
    @pytest.mark.parametrize(
        "text",
        [
            "DELETE the old records",  # shouting
            "d-e-l-e-t-e the archive",  # hyphen-spaced letters collapse to one token
            "sÉnd the update to everyone",  # accent smuggling
            "  tidy   up\tthe\nrecords  ",  # whitespace games
        ],
    )
    def test_obfuscated_phrasing_still_routes_high_impact(self, text: str) -> None:
        assert classify_text(text).high_impact, text
