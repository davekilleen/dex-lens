"""CI inventory check (g2-inventory-check): uninventoried fields fail the build."""

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_inventory.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("check_inventory", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def check_inventory():
    return load_script_module()


@pytest.fixture()
def fake_module():
    """Install a synthetic capability_exchange submodule, then remove it."""
    name = "capability_exchange._g2_check_probe"
    module = types.ModuleType(name)
    sys.modules[name] = module
    try:
        yield module
    finally:
        del sys.modules[name]


class TestScriptOnRealTree:
    def test_current_tree_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestProblemDetection:
    def test_uninventoried_model_field_is_a_problem(self, check_inventory, fake_module) -> None:
        from capability_exchange.boundary.serialization import InventoriedModel

        class RogueRecord(InventoriedModel):
            undeclared_blob: str

        RogueRecord.__module__ = fake_module.__name__
        fake_module.RogueRecord = RogueRecord

        problems = check_inventory.collect_problems()
        assert any("RogueRecord.undeclared_blob" in p for p in problems)

    def test_plain_basemodel_outside_allowlist_is_a_problem(
        self, check_inventory, fake_module
    ) -> None:
        class LooseModel(BaseModel):
            anything: str

        LooseModel.__module__ = fake_module.__name__
        fake_module.LooseModel = LooseModel

        problems = check_inventory.collect_problems()
        assert any("LooseModel" in p for p in problems)

    def test_clean_tree_reports_no_problems(self, check_inventory) -> None:
        assert check_inventory.collect_problems() == []

    def test_class_name_collision_is_a_problem(self, check_inventory, fake_module) -> None:
        """Adversarial M1 finding: the inventory namespace is keyed by bare
        class name, so a second model that reuses an inventoried model's
        class name silently inherits its entries and serializes fields that
        were never inventoried.

        The namespace is flat by design, so uniqueness must be enforced —
        otherwise "every field has an inventory entry" is satisfiable by
        collision rather than by declaration.
        """
        from capability_exchange.boundary.serialization import InventoriedModel

        class EvidenceItem(InventoriedModel):  # deliberate collision
            state: str = "observed"
            captured_at: str = ""
            stale_after: str | None = None
            reference: str = "SMUGGLED-PRIVATE-PAYLOAD"

        EvidenceItem.__module__ = fake_module.__name__
        fake_module.EvidenceItem = EvidenceItem

        problems = check_inventory.collect_problems()
        assert any("EvidenceItem" in p and "collision" in p.lower() for p in problems), problems

    def test_inventory_entry_without_matching_model_is_a_problem(self, check_inventory) -> None:
        from capability_exchange.boundary.inventory import (
            FieldEntry,
            Inventory,
            use_inventory,
        )

        drifted = Inventory(
            inventory_version=1,
            fields={
                "VanishedModel.old_field": FieldEntry(
                    description="d",
                    collection="c",
                    derivation="n",
                    display="d",
                    storage=None,
                    sharing="never",
                    deletion="not-stored",
                    audit="none",
                )
            },
        )
        with use_inventory(drifted):
            problems = check_inventory.collect_problems()
        assert any("VanishedModel.old_field" in p for p in problems)
