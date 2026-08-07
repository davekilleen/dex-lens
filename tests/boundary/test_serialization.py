"""G2 typed serialization boundary: only inventoried fields are serializable.

A model field without an inventory entry raises at any serialization
attempt — it is non-persistable and non-transmittable by construction.
Default processing is ephemeral: nothing reaches a storage payload unless
its inventory entry declares storage, and nothing reaches a transmission
payload unless its entry declares sharing (no M1 field does).
"""

import keyword

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import create_model

from capability_exchange.boundary.inventory import (
    FieldEntry,
    Inventory,
    StorageDeclaration,
    use_inventory,
)
from capability_exchange.boundary.serialization import (
    EphemeralByDefaultError,
    InventoriedModel,
    NoTransmissibleFieldsError,
    UninventoriedFieldError,
)


def entry(*, stored: bool = False) -> FieldEntry:
    return FieldEntry(
        description="test field",
        collection="synthesized in test",
        derivation="none",
        display="not displayed",
        storage=(
            StorageDeclaration(location="test file", duration="until deleted")
            if stored
            else None
        ),
        sharing="never",
        deletion="delete-test-artifacts" if stored else "not-stored",
        audit="none",
    )


def make_inventory(fields: dict[str, FieldEntry]) -> Inventory:
    return Inventory(inventory_version=1, fields=fields)


class Inventoried(InventoriedModel):
    alpha: str
    beta: int


class HasPrivateExtra(InventoriedModel):
    alpha: str
    secret_note: str  # deliberately never inventoried


class Outer(InventoriedModel):
    label: str
    inner: HasPrivateExtra


INVENTORIED_ONLY = make_inventory(
    {
        "Inventoried.alpha": entry(),
        "Inventoried.beta": entry(stored=True),
        "HasPrivateExtra.alpha": entry(),
        "Outer.label": entry(),
        "Outer.inner": entry(),
    }
)


class TestOnlyInventoriedFieldsSerialize:
    def test_fully_inventoried_model_dumps(self) -> None:
        with use_inventory(INVENTORIED_ONLY):
            m = Inventoried(alpha="a", beta=1)
            assert m.model_dump() == {"alpha": "a", "beta": 1}
            assert '"alpha":"a"' in m.model_dump_json()

    def test_uninventoried_field_raises_on_model_dump(self) -> None:
        with use_inventory(INVENTORIED_ONLY):
            m = HasPrivateExtra(alpha="a", secret_note="private")
            with pytest.raises(UninventoriedFieldError, match="secret_note"):
                m.model_dump()

    def test_uninventoried_field_raises_on_model_dump_json(self) -> None:
        with use_inventory(INVENTORIED_ONLY):
            m = HasPrivateExtra(alpha="a", secret_note="private")
            with pytest.raises(UninventoriedFieldError):
                m.model_dump_json()

    def test_nested_uninventoried_field_raises_from_parent_dump(self) -> None:
        # The guard must hold for models nested inside other models: an
        # uninventoried field cannot ride out inside a parent's payload.
        with use_inventory(INVENTORIED_ONLY):
            outer = Outer(label="ok", inner=HasPrivateExtra(alpha="a", secret_note="p"))
            with pytest.raises(UninventoriedFieldError, match="secret_note"):
                outer.model_dump()

    def test_error_message_is_honest_and_names_the_field(self) -> None:
        with use_inventory(INVENTORIED_ONLY):
            m = HasPrivateExtra(alpha="a", secret_note="private")
            with pytest.raises(UninventoriedFieldError) as exc:
                m.model_dump()
            msg = str(exc.value)
            assert "HasPrivateExtra.secret_note" in msg
            assert "private" not in msg.split("HasPrivateExtra.secret_note")[0]

    @settings(max_examples=25, deadline=None)
    @given(
        name=st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True).filter(
            lambda s: not keyword.iskeyword(s)
            and not s.startswith("model_")
            and not hasattr(InventoriedModel, s)
        )
    )
    def test_any_uninventoried_field_name_refuses_serialization(self, name: str) -> None:
        model_cls = create_model("PropertyProbe", __base__=InventoriedModel, **{name: (str, ...)})
        with use_inventory(INVENTORIED_ONLY):
            instance = model_cls(**{name: "value"})
            with pytest.raises(UninventoriedFieldError):
                instance.model_dump()


class TestEphemeralByDefault:
    def test_storage_payload_contains_only_storage_declared_fields(self) -> None:
        with use_inventory(INVENTORIED_ONLY):
            m = Inventoried(alpha="a", beta=2)
            assert m.dump_for_storage() == {"beta": 2}

    def test_model_with_no_stored_fields_refuses_storage_dump(self) -> None:
        # Default processing is ephemeral: with no storage declaration there
        # is no storage payload at all — refusal, not an empty write.
        with use_inventory(INVENTORIED_ONLY):
            m = HasPrivateExtra(alpha="a", secret_note="p")
            with pytest.raises((EphemeralByDefaultError, UninventoriedFieldError)):
                m.dump_for_storage()

    def test_fully_ephemeral_model_refuses_storage_dump(self) -> None:
        ephemeral_inv = make_inventory({"Inventoried.alpha": entry(), "Inventoried.beta": entry()})
        with use_inventory(ephemeral_inv):
            m = Inventoried(alpha="a", beta=2)
            with pytest.raises(EphemeralByDefaultError):
                m.dump_for_storage()

    def test_storage_dump_still_refuses_uninventoried_fields(self) -> None:
        with use_inventory(INVENTORIED_ONLY):
            m = HasPrivateExtra(alpha="a", secret_note="p")
            with pytest.raises(UninventoriedFieldError):
                m.dump_for_storage()

    def test_no_m1_field_is_transmissible(self) -> None:
        # Every M1 inventory entry declares sharing: never, so every
        # transmission dump refuses. Diagnosis is telemetry-free.
        with use_inventory(INVENTORIED_ONLY):
            m = Inventoried(alpha="a", beta=2)
            with pytest.raises(NoTransmissibleFieldsError):
                m.dump_for_transmission()

    def test_packaged_inventory_permits_no_transmission_at_all(self) -> None:
        # Against the real packaged inventory (not a test substitute):
        # zero fields declare sharing other than "never".
        from capability_exchange.boundary.inventory import load_packaged_inventory

        for key, field_entry in load_packaged_inventory().fields.items():
            assert field_entry.sharing == "never", f"{key} declares sharing"
