"""G2 data inventory: schema-validated, machine-readable, fail-closed.

The inventory is the single source of truth for every field the product
persists or transmits. Every entry declares collection, derivation, display,
storage, sharing, deletion, and audit. Anything unparseable or incomplete
fails validation outright — a field without a valid entry is private,
non-persistable, non-transmittable.
"""

import pytest

from capability_exchange.boundary import inventory as inv_mod
from capability_exchange.boundary.inventory import (
    FieldEntry,
    Inventory,
    InventoryError,
    active_inventory,
    load_inventory_text,
    load_packaged_inventory,
)

VALID_ENTRY_BODY = """\
    description: "example field"
    collection: "collected locally during inspection"
    derivation: "none"
    display: "shown in the local report only"
    storage: none
    sharing: never
    deletion: not-stored
    audit: "no audit trail; ephemeral"
"""


def make_doc(entry_body: str = VALID_ENTRY_BODY, key: str = "ExampleModel.field_a") -> str:
    return f"inventory_version: 1\nfields:\n  {key}:\n{entry_body}"


class TestPackagedInventory:
    def test_packaged_inventory_loads_and_validates(self) -> None:
        inv = load_packaged_inventory()
        assert isinstance(inv, Inventory)
        assert inv.inventory_version == 2
        assert inv.fields, "packaged inventory must not be empty"

    def test_import_time_inventory_is_active(self) -> None:
        # The module validates the packaged YAML at import; the active
        # inventory is that validated object.
        assert active_inventory().fields == load_packaged_inventory().fields

    def test_every_entry_key_names_model_and_field(self) -> None:
        for key in load_packaged_inventory().fields:
            model, _, field = key.partition(".")
            assert model and field, f"bad inventory key: {key!r}"

    def test_stored_entries_declare_a_deletion_path(self) -> None:
        for key, entry in load_packaged_inventory().fields.items():
            if entry.storage is not None:
                assert entry.deletion != "not-stored", (
                    f"{key} declares storage but no deletion path"
                )
            else:
                assert entry.deletion == "not-stored", (
                    f"{key} is ephemeral but names a deletion path"
                )


class TestSchemaFailsClosed:
    def test_valid_document_parses(self) -> None:
        inv = load_inventory_text(make_doc())
        assert "ExampleModel.field_a" in inv.fields

    @pytest.mark.parametrize(
        "missing",
        ["description", "collection", "derivation", "display", "storage", "sharing",
         "deletion", "audit"],
    )
    def test_missing_declaration_rejected(self, missing: str) -> None:
        body = "\n".join(
            line for line in VALID_ENTRY_BODY.splitlines()
            if not line.strip().startswith(f"{missing}:")
        ) + "\n"
        with pytest.raises(InventoryError):
            load_inventory_text(make_doc(body))

    def test_unknown_declaration_key_rejected(self) -> None:
        body = VALID_ENTRY_BODY + '    telemetry: "surprise"\n'
        with pytest.raises(InventoryError):
            load_inventory_text(make_doc(body))

    def test_storage_declared_without_deletion_path_rejected(self) -> None:
        body = VALID_ENTRY_BODY.replace(
            "    storage: none\n",
            '    storage:\n      location: "local file"\n      duration: "until deleted"\n',
        )
        # deletion still says not-stored -> contradiction -> reject
        with pytest.raises(InventoryError):
            load_inventory_text(make_doc(body))

    def test_deletion_path_on_ephemeral_field_rejected(self) -> None:
        body = VALID_ENTRY_BODY.replace(
            "    deletion: not-stored\n", "    deletion: delete-something\n"
        )
        with pytest.raises(InventoryError):
            load_inventory_text(make_doc(body))

    def test_only_the_exact_contribution_manifest_field_may_declare_sharing(self) -> None:
        body = VALID_ENTRY_BODY.replace(
            "    sharing: never\n",
            "    sharing: contribution-intake-exact-manifest\n",
        )
        allowed = load_inventory_text(make_doc(body, key="DisclosureManifest.display_text"))
        assert allowed.fields["DisclosureManifest.display_text"].shares
        with pytest.raises(InventoryError):
            load_inventory_text(make_doc(body))

    def test_bad_key_shape_rejected(self) -> None:
        with pytest.raises(InventoryError):
            load_inventory_text(make_doc(key="no_model_prefix"))

    def test_duplicate_keys_rejected(self) -> None:
        doc = make_doc() + "  ExampleModel.field_a:\n" + VALID_ENTRY_BODY
        with pytest.raises(InventoryError):
            load_inventory_text(doc)

    @pytest.mark.parametrize(
        "doc",
        [
            "",  # empty
            "fields:\n",  # missing version
            "inventory_version: 1\n",  # missing fields
            "inventory_version: 1\nfields: []\n",  # flow syntax not in subset
            "inventory_version: 1\nfields:\n\t X.y:\n",  # tab indentation
            "not yaml at all {{{",
        ],
    )
    def test_malformed_documents_rejected(self, doc: str) -> None:
        with pytest.raises(InventoryError):
            load_inventory_text(doc)


class TestUseInventoryForTests:
    def test_use_inventory_swaps_and_restores(self) -> None:
        original = active_inventory()
        substitute = Inventory(
            inventory_version=1,
            fields={"Other.field": FieldEntry.model_validate({
                "description": "d", "collection": "c", "derivation": "n",
                "display": "d", "storage": None, "sharing": "never",
                "deletion": "not-stored", "audit": "none",
            })},
        )
        with inv_mod.use_inventory(substitute):
            assert active_inventory() is substitute
        assert active_inventory() is original
