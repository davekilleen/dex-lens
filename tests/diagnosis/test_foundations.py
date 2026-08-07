"""The eight Foundation Capabilities encoded as data (#351; M-D).

Each has a defined user job, observable evidence, and a safety boundary,
plus negative rules — including the four the #351 resolution names.
"""

from __future__ import annotations

import re

import pytest

from capability_exchange.diagnosis import (
    FOUNDATION_DEFINITIONS,
    CapabilityState,
    FoundationCapability,
    FoundationDefinition,
    NegativeRule,
    definition_for,
    negative_rule_ids,
)

_KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


class TestEightCapabilities:
    def test_exactly_eight_capabilities_exist(self) -> None:
        assert len(FoundationCapability) == 8

    def test_the_eight_are_the_351_set(self) -> None:
        assert {member.value for member in FoundationCapability} == {
            "ownership-portability",
            "privacy-minimal-disclosure",
            "context-orientation",
            "durable-memory-provenance",
            "scoped-agency-human-control",
            "safe-change-recovery",
            "honest-health-observability",
            "compounding-correctability",
        }

    def test_definitions_cover_exactly_the_eight(self) -> None:
        assert set(FOUNDATION_DEFINITIONS) == set(FoundationCapability)

    def test_definition_for_is_total(self) -> None:
        for capability in FoundationCapability:
            definition = definition_for(capability)
            assert definition.capability is capability


@pytest.mark.parametrize("capability", list(FoundationCapability))
class TestEveryDefinitionIsComplete:
    def test_defined_user_job(self, capability: FoundationCapability) -> None:
        assert definition_for(capability).user_job.strip()

    def test_observable_evidence(self, capability: FoundationCapability) -> None:
        definition = definition_for(capability)
        assert definition.observable_evidence
        assert all(entry.strip() for entry in definition.observable_evidence)

    def test_safety_boundary(self, capability: FoundationCapability) -> None:
        assert definition_for(capability).safety_boundary.strip()

    def test_at_least_one_negative_rule(self, capability: FoundationCapability) -> None:
        definition = definition_for(capability)
        assert definition.negative_rules
        for rule in definition.negative_rules:
            assert _KEBAB.match(rule.rule_id)
            assert rule.statement.strip()

    def test_outcome_and_configuration_patterns_declared(
        self, capability: FoundationCapability
    ) -> None:
        definition = definition_for(capability)
        assert definition.outcome_probe_patterns
        assert definition.configuration_probe_patterns
        assert definition.boundary_probe_patterns
        assert definition.overbroad_probe_patterns

    def test_outcome_patterns_disjoint_from_configuration(
        self, capability: FoundationCapability
    ) -> None:
        """A probe class is unambiguous: no pattern is both outcome and
        configuration for the same capability."""
        definition = definition_for(capability)
        assert not set(definition.outcome_probe_patterns) & set(
            definition.configuration_probe_patterns
        )

    def test_next_moves_cover_exactly_the_capability_states(
        self, capability: FoundationCapability
    ) -> None:
        definition = definition_for(capability)
        assert set(definition.next_moves) == {state.value for state in CapabilityState}
        for move in definition.next_moves.values():
            assert move.strip()

    def test_practical_implication_present(self, capability: FoundationCapability) -> None:
        assert definition_for(capability).practical_implication.strip()


class TestNamedNegativeRules:
    """The four negative rules the #351 resolution names, on their capability."""

    def _rule_ids(self, capability: FoundationCapability) -> set[str]:
        return {rule.rule_id for rule in definition_for(capability).negative_rules}

    def test_read_access_never_implies_write_permission(self) -> None:
        assert "read-access-never-implies-write-permission" in self._rule_ids(
            FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL
        )

    def test_file_presence_never_means_healthy(self) -> None:
        assert "file-presence-never-means-healthy" in self._rule_ids(
            FoundationCapability.HONEST_HEALTH_OBSERVABILITY
        )

    def test_chat_history_alone_is_not_memory_proof(self) -> None:
        assert "chat-history-alone-is-not-memory-proof" in self._rule_ids(
            FoundationCapability.DURABLE_MEMORY_PROVENANCE
        )

    def test_no_autonomous_permanent_self_modification(self) -> None:
        assert "no-autonomous-permanent-self-modification" in self._rule_ids(
            FoundationCapability.COMPOUNDING_CORRECTABILITY
        )

    def test_negative_rule_ids_are_unique_across_capabilities(self) -> None:
        all_rules = [
            rule.rule_id
            for definition in FOUNDATION_DEFINITIONS.values()
            for rule in definition.negative_rules
        ]
        assert len(all_rules) == len(set(all_rules))
        assert negative_rule_ids() == frozenset(all_rules)


class TestDataIsImmutable:
    def test_definitions_are_frozen(self) -> None:
        definition = definition_for(FoundationCapability.OWNERSHIP_PORTABILITY)
        with pytest.raises(AttributeError):
            definition.user_job = "changed"  # type: ignore[misc]

    def test_negative_rules_are_frozen(self) -> None:
        rule = definition_for(FoundationCapability.OWNERSHIP_PORTABILITY).negative_rules[0]
        with pytest.raises(AttributeError):
            rule.statement = "changed"  # type: ignore[misc]

    def test_definitions_mapping_rejects_mutation(self) -> None:
        with pytest.raises(TypeError):
            FOUNDATION_DEFINITIONS[  # type: ignore[index]
                FoundationCapability.OWNERSHIP_PORTABILITY
            ] = None

    def test_next_moves_must_cover_all_states(self) -> None:
        with pytest.raises(ValueError, match="next_moves"):
            FoundationDefinition(
                capability=FoundationCapability.OWNERSHIP_PORTABILITY,
                user_job="job",
                observable_evidence=("evidence",),
                safety_boundary="boundary",
                negative_rules=(NegativeRule(rule_id="a-rule", statement="never"),),
                outcome_probe_patterns=("outcome",),
                configuration_probe_patterns=("config",),
                boundary_probe_patterns=("boundary",),
                overbroad_probe_patterns=("beyond",),
                practical_implication="matters",
                next_moves={"working": "only one state covered"},
            )
