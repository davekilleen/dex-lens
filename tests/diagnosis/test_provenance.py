"""Source-aware, privacy-safe diagnosis provenance."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from capability_exchange.boundary.secret_markers import (
    SECRET_SHAPE_EXAMPLES,
    SecretShapeExample,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    SafeAttribute,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

NOW = datetime(2026, 8, 27, tzinfo=UTC)
SCOPE_DIGEST = "scope:sha256:" + "a" * 64


def _provenance(source_id: str, source_class: str) -> dict[str, object]:
    return {
        "source_id": f"scope:{source_id}",
        "source_class": source_class,
        "scope_reference": SCOPE_DIGEST,
        "relative_reference": ".claude/skills/planner/SKILL.md",
    }


def _skill(source_id: str, source_class: str) -> Observation:
    return Observation(
        kind=ObservationKind.SKILL,
        identity="planner",
        label="Planner",
        operational_state=OperationalState.IMPLEMENTED,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference=f"file:{source_id}-planner",
        ),
        provenance=_provenance(source_id, source_class),
    )


def test_same_identity_from_two_sources_is_not_collapsed() -> None:
    vault = _skill("vault", "vault-authored")
    global_home = _skill("global", "user-global")

    fingerprint = EvidenceFingerprint(
        adapter_id="claude-code-local",
        collected_at=NOW,
        observations=(vault, global_home),
    )

    assert [item.provenance.source_id for item in fingerprint.observations] == [
        "scope:vault",
        "scope:global",
    ]


def test_duplicate_kind_identity_and_source_id_is_rejected() -> None:
    item = _skill("vault", "vault-authored")

    with pytest.raises(ValidationError, match="duplicate observation"):
        EvidenceFingerprint(
            adapter_id="claude-code-local",
            collected_at=NOW,
            observations=(item, item),
        )


@pytest.mark.parametrize(
    "relative_reference",
    (
        "/Users/person/private/SKILL.md",
        "\\server\\private\\SKILL.md",
        "~/private/SKILL.md",
        "~alice/private/SKILL.md",
        "$HOME/private/SKILL.md",
        "$HOME\\private\\SKILL.md",
        "${HOME}/private/SKILL.md",
        "${HOME}\\private\\SKILL.md",
        "skills/../private/SKILL.md",
        "skills\\..\\private\\SKILL.md",
        "skills/secret-token/SKILL.md",
        "skills/planner/secrets.env",
        "skills/planner/credentials.json",
        "skills/planner/private_key.pem",
        "skills/planner/api_key.env",
        "skills/planner/api-key.json",
        "skills/planner/apikey.txt",
        "skills/planner/passwd",
        "skills/planner\n/SKILL.md",
        "skills/planner\x7f/SKILL.md",
        "skills/planner\u0085/SKILL.md",
        "-----BEGIN PRIVATE KEY-----",
    ),
)
def test_relative_source_reference_refuses_raw_or_secret_shaped_values(
    relative_reference: str,
) -> None:
    provenance = {
        **_provenance("vault", "vault-authored"),
        "relative_reference": relative_reference,
    }

    with pytest.raises(ValidationError, match="relative_reference"):
        Observation(
            kind=ObservationKind.SKILL,
            identity="planner",
            label="Planner",
            operational_state=OperationalState.IMPLEMENTED,
            evidence=EvidenceItem(
                state=EvidenceState.OBSERVED,
                captured_at=NOW,
                reference="file:planner",
            ),
            provenance=provenance,
        )


@pytest.mark.parametrize(
    "relative_reference",
    (
        ".claude/skills/planner/SKILL.md",
        "skills/planner-v2/README.md",
        "sha256:" + "b" * 16,
    ),
)
def test_legitimate_relative_source_references_are_accepted(
    relative_reference: str,
) -> None:
    observation = Observation(
        kind=ObservationKind.SKILL,
        identity="planner",
        label="Planner",
        operational_state=OperationalState.IMPLEMENTED,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference="file:planner",
        ),
        provenance={
            **_provenance("vault", "vault-authored"),
            "relative_reference": relative_reference,
        },
    )

    assert observation.provenance.relative_reference == relative_reference


@pytest.mark.parametrize("shape", SECRET_SHAPE_EXAMPLES, ids=lambda shape: shape.name)
def test_shared_secret_shape_catalogue_is_rejected_from_relative_paths(
    shape: SecretShapeExample,
) -> None:
    relative_reference = f"skills/{shape.path_fragment}/SKILL.md"

    with pytest.raises(ValidationError, match="relative_reference"):
        Observation(
            kind=ObservationKind.SKILL,
            identity="planner",
            label="Planner",
            operational_state=OperationalState.IMPLEMENTED,
            evidence=EvidenceItem(
                state=EvidenceState.OBSERVED,
                captured_at=NOW,
                reference="file:planner",
            ),
            provenance={
                **_provenance("vault", "vault-authored"),
                "relative_reference": relative_reference,
            },
        )


def test_source_models_are_closed_and_exact() -> None:
    invalid = _provenance("vault", "private-machine-folder")

    with pytest.raises(ValidationError, match="source_class"):
        Observation(
            kind=ObservationKind.SKILL,
            identity="planner",
            label="Planner",
            operational_state=OperationalState.IMPLEMENTED,
            evidence=EvidenceItem(
                state=EvidenceState.OBSERVED,
                captured_at=NOW,
                reference="file:planner",
            ),
            provenance=invalid,
        )

    with pytest.raises(ValidationError, match="extra"):
        Observation(
            kind=ObservationKind.SKILL,
            identity="planner",
            label="Planner",
            operational_state=OperationalState.IMPLEMENTED,
            evidence=EvidenceItem(
                state=EvidenceState.OBSERVED,
                captured_at=NOW,
                reference="file:planner",
            ),
            provenance={**_provenance("vault", "vault-authored"), "raw_root": "/tmp"},
        )


def test_copy_routes_cannot_bypass_provenance_validation() -> None:
    observation = _skill("vault", "vault-authored")

    with pytest.raises(ValidationError, match="relative_reference"):
        observation.provenance.model_copy(
            update={"relative_reference": "/Users/person/private/SKILL.md"}
        )
    with pytest.raises(ValidationError, match="relative_reference"):
        observation.model_copy(
            update={
                "provenance": {
                    **_provenance("vault", "vault-authored"),
                    "relative_reference": "skills/../private/SKILL.md",
                }
            }
        )


def test_construct_routes_cannot_bypass_provenance_validation() -> None:
    observation = _skill("vault", "vault-authored")
    provenance_values = {
        field_name: getattr(observation.provenance, field_name)
        for field_name in type(observation.provenance).model_fields
    }
    provenance_values["relative_reference"] = "$HOME/private/SKILL.md"

    with pytest.raises(ValidationError, match="relative_reference"):
        type(observation.provenance).model_construct(**provenance_values)

    observation_values = {
        field_name: getattr(observation, field_name)
        for field_name in type(observation).model_fields
    }
    observation_values["provenance"] = provenance_values
    with pytest.raises(ValidationError, match="relative_reference"):
        type(observation).model_construct(**observation_values)


def test_observation_provenance_cannot_be_replaced_after_construction() -> None:
    vault = _skill("vault", "vault-authored")
    global_home = _skill("global", "user-global")

    with pytest.raises(ValueError, match="provenance.*locked"):
        vault.model_copy(update={"provenance": global_home.provenance})


@pytest.mark.parametrize(
    "state",
    (
        OperationalState.IMPLEMENTED,
        OperationalState.LOADED,
        OperationalState.OUTCOME_VERIFIED,
    ),
)
def test_working_copy_observations_are_centrally_not_assessed(
    state: OperationalState,
) -> None:
    observation = Observation(
        kind=ObservationKind.SKILL,
        identity="planner",
        label="Planner",
        operational_state=state,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference="file:working-planner",
        ),
        provenance=_provenance("working-copy", "working-copy"),
    )

    assert observation.operational_state is OperationalState.NOT_ASSESSED
    assert (
        observation.model_copy(
            update={"operational_state": OperationalState.OUTCOME_VERIFIED}
        ).operational_state
        is OperationalState.NOT_ASSESSED
    )


def test_working_copy_construct_route_cannot_introduce_active_state() -> None:
    observation = _skill("working-copy", "working-copy")
    values = {
        field_name: getattr(observation, field_name)
        for field_name in type(observation).model_fields
    }
    values["operational_state"] = OperationalState.LOADED

    constructed = type(observation).model_construct(**values)

    assert constructed.operational_state is OperationalState.NOT_ASSESSED


def test_fingerprint_copy_and_construct_reject_duplicate_source_triples() -> None:
    item = _skill("vault", "vault-authored")
    fingerprint = EvidenceFingerprint(
        adapter_id="claude-code-local",
        collected_at=NOW,
        observations=(item,),
    )

    with pytest.raises(ValidationError, match="duplicate observation"):
        fingerprint.model_copy(update={"observations": (item, item)})
    with pytest.raises(ValidationError, match="duplicate observation"):
        EvidenceFingerprint.model_construct(
            adapter_id="claude-code-local",
            collected_at=NOW,
            observations=(item, item),
        )


def test_deprecated_copy_is_blocked_for_every_task_two_invariant_model() -> None:
    vault = _skill("vault", "vault-authored")
    global_home = _skill("global", "user-global")
    working_copy = _skill("working-copy", "working-copy")
    fingerprint = EvidenceFingerprint(
        adapter_id="claude-code-local",
        collected_at=NOW,
        observations=(vault,),
    )
    attribute = SafeAttribute(key="source-kind", value="plist")

    with pytest.raises(TypeError, match="model_copy"):
        vault.provenance.copy(update={"relative_reference": "/private/SKILL.md"})
    with pytest.raises(TypeError, match="model_copy"):
        vault.copy(update={"provenance": global_home.provenance})
    with pytest.raises(TypeError, match="model_copy"):
        working_copy.copy(update={"operational_state": OperationalState.LOADED})
    with pytest.raises(TypeError, match="model_copy"):
        fingerprint.copy(update={"observations": (vault, vault)})
    with pytest.raises(TypeError, match="model_copy"):
        attribute.copy(update={"value": "secret-token"})


def test_safe_attribute_validators_hold_on_copy_and_construct_routes() -> None:
    attribute = SafeAttribute(key="source-kind", value="plist")

    with pytest.raises(ValidationError, match="secret-shaped"):
        attribute.model_copy(update={"value": "secret-token"})
    with pytest.raises(ValidationError, match="secret-shaped"):
        SafeAttribute.model_construct(key="source-kind", value="secret-token")
