"""Versioned Host Adapter contract (HANDOFF 2.3 M-A; gates.md G1).

The contract declares discoverable roots, explicit read scope, denied paths,
symlink/archive policy, supported evidence probes, version detection method,
and mode. A host with no ownership/mutation contract is Diagnose-only BY
DEFAULT, and Adapt-capable is unrepresentable in M1 because the mutation
contract it requires is a forward-declared type that cannot be constructed
until M4 builds it.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from capability_exchange.adapter.contract import (
    AdaptCapableUnrepresentableError,
    AdapterContract,
    AdapterMode,
    ArchivePolicy,
    MutationContractRef,
    MutationContractUnavailableError,
    SymlinkPolicy,
    VersionDetectionMethod,
)
from capability_exchange.boundary.serialization import (
    EphemeralByDefaultError,
    NoTransmissibleFieldsError,
)


def valid_kwargs(**overrides: object) -> dict[str, object]:
    """A coherent Diagnose-only contract shaped like the Claude Code adapter."""
    kwargs: dict[str, object] = {
        "adapter_id": "claude-code-macos",
        "contract_version": "1.0.0",
        "discoverable_roots": ("~/.claude", "~/projects"),
        "read_scope": ("~/.claude/settings.json", "~/.claude/skills", "~/projects"),
        "denied_paths": ("~/.claude/secrets", "~/.ssh", "~/.aws"),
        "symlink_policy": SymlinkPolicy.RESOLVE_AND_REJECT_ESCAPES,
        "archive_policy": ArchivePolicy.DO_NOT_OPEN,
        "evidence_probes": ("skills-present", "memory-files", "settings-readable"),
        "version_detection": VersionDetectionMethod.FILE_MARKER,
    }
    kwargs.update(overrides)
    return kwargs


class TestContractValidation:
    def test_valid_diagnose_only_contract_constructs(self) -> None:
        contract = AdapterContract(**valid_kwargs())
        assert contract.adapter_id == "claude-code-macos"
        assert contract.mode is AdapterMode.DIAGNOSE_ONLY

    def test_mode_defaults_to_diagnose_only(self) -> None:
        # A host with no ownership/mutation contract is Diagnose-only BY
        # DEFAULT (#348: "no host-specific ownership and rewind contract
        # means Diagnose-only").
        contract = AdapterContract(**valid_kwargs())
        assert contract.mode is AdapterMode.DIAGNOSE_ONLY
        assert contract.mutation_contract is None

    def test_scope_outside_all_roots_rejected(self) -> None:
        with pytest.raises(ValidationError, match="read_scope"):
            AdapterContract(**valid_kwargs(read_scope=("/etc/passwd",)))

    def test_scope_containment_is_by_path_component_not_string_prefix(self) -> None:
        # "~/projects-secret" is NOT under the root "~/projects".
        with pytest.raises(ValidationError, match="read_scope"):
            AdapterContract(**valid_kwargs(read_scope=("~/projects-secret",)))

    def test_scope_entirely_denied_is_incoherent(self) -> None:
        # A scope entry wholly covered by a denied path is dead scope.
        with pytest.raises(ValidationError, match="denied"):
            AdapterContract(**valid_kwargs(denied_paths=("~/.claude",)))

    def test_denied_path_inside_scope_is_coherent(self) -> None:
        contract = AdapterContract(
            **valid_kwargs(denied_paths=("~/projects/notes", "~/.ssh"))
        )
        assert "~/projects/notes" in contract.denied_paths

    def test_relative_path_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdapterContract(**valid_kwargs(discoverable_roots=("projects/x",)))

    def test_traversal_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdapterContract(**valid_kwargs(read_scope=("~/projects/../.ssh",)))

    def test_entire_filesystem_never_an_explicit_scope(self) -> None:
        with pytest.raises(ValidationError):
            AdapterContract(**valid_kwargs(discoverable_roots=("/",)))

    def test_entire_home_never_an_explicit_read_scope(self) -> None:
        with pytest.raises(ValidationError):
            AdapterContract(**valid_kwargs(discoverable_roots=("~",), read_scope=("~",)))

    def test_duplicate_entries_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            AdapterContract(
                **valid_kwargs(read_scope=("~/projects", "~/projects"))
            )

    def test_symlink_policy_is_a_closed_vocabulary(self) -> None:
        with pytest.raises(ValidationError):
            AdapterContract(**valid_kwargs(symlink_policy="follow-all"))
        assert {p.value for p in SymlinkPolicy} == {
            "resolve-and-reject-escapes",
            "refuse-all",
        }

    def test_archive_policy_has_no_extracting_member(self) -> None:
        assert {p.value for p in ArchivePolicy} == {"do-not-open", "list-names-only"}

    def test_version_detection_has_no_exec_shaped_member(self) -> None:
        # G1: no arbitrary shell from the inspection process — a version
        # detection method that runs a command is unrepresentable.
        assert {m.value for m in VersionDetectionMethod} == {
            "file-marker",
            "package-manifest",
            "user-reported",
            "unknown",
        }

    def test_probe_ids_must_be_kebab_case(self) -> None:
        with pytest.raises(ValidationError):
            AdapterContract(**valid_kwargs(evidence_probes=("Skills Present!",)))

    def test_probe_ids_must_be_unique(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            AdapterContract(**valid_kwargs(evidence_probes=("a-probe", "a-probe")))

    def test_at_least_one_probe_required(self) -> None:
        with pytest.raises(ValidationError):
            AdapterContract(**valid_kwargs(evidence_probes=()))

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdapterContract(**valid_kwargs(heal=True))

    def test_contract_is_frozen(self) -> None:
        contract = AdapterContract(**valid_kwargs())
        with pytest.raises(ValidationError):
            contract.mode = AdapterMode.ADAPT_CAPABLE  # type: ignore[misc]


class TestAdaptCapableUnrepresentableInM1:
    """Adapt-capable requires a mutation-contract reference, and the
    reference type cannot be constructed until M4 builds the real thing."""

    def test_mutation_contract_ref_init_raises(self) -> None:
        with pytest.raises(MutationContractUnavailableError):
            MutationContractRef()

    def test_mutation_contract_ref_model_validate_raises(self) -> None:
        with pytest.raises(MutationContractUnavailableError):
            MutationContractRef.model_validate({})

    def test_mutation_contract_ref_model_construct_raises(self) -> None:
        # model_construct skips validation; the forward declaration must
        # close that route too.
        with pytest.raises(MutationContractUnavailableError):
            MutationContractRef.model_construct()

    @settings(max_examples=25, deadline=None)
    @given(payload=st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3))
    def test_no_payload_constructs_a_mutation_contract(self, payload: dict) -> None:
        with pytest.raises(MutationContractUnavailableError):
            MutationContractRef.model_validate(payload)

    def test_adapt_capable_without_mutation_contract_refuses(self) -> None:
        with pytest.raises(AdaptCapableUnrepresentableError, match="Diagnose-only"):
            AdapterContract(**valid_kwargs(mode=AdapterMode.ADAPT_CAPABLE))

    def test_adapt_capable_via_string_mode_refuses(self) -> None:
        with pytest.raises(AdaptCapableUnrepresentableError):
            AdapterContract(**valid_kwargs(mode="adapt-capable"))

    def test_adapt_capable_via_mutation_contract_payload_refuses(self) -> None:
        with pytest.raises(MutationContractUnavailableError):
            AdapterContract.model_validate(
                valid_kwargs(mode="adapt-capable", mutation_contract={})
            )

    def test_adapt_capable_via_model_copy_update_refuses(self) -> None:
        contract = AdapterContract(**valid_kwargs())
        with pytest.raises(AdaptCapableUnrepresentableError):
            contract.model_copy(update={"mode": AdapterMode.ADAPT_CAPABLE})

    def test_adapt_capable_via_model_construct_refuses(self) -> None:
        with pytest.raises(AdaptCapableUnrepresentableError):
            AdapterContract.model_construct(**valid_kwargs(mode="adapt-capable"))


class TestContractSerializationBoundary:
    def test_round_trips_through_the_g2_boundary(self) -> None:
        contract = AdapterContract(**valid_kwargs())
        assert AdapterContract.model_validate(contract.model_dump()) == contract

    def test_contract_is_ephemeral_by_default(self) -> None:
        contract = AdapterContract(**valid_kwargs())
        with pytest.raises(EphemeralByDefaultError):
            contract.dump_for_storage()

    def test_contract_is_never_transmissible(self) -> None:
        contract = AdapterContract(**valid_kwargs())
        with pytest.raises(NoTransmissibleFieldsError):
            contract.dump_for_transmission()
