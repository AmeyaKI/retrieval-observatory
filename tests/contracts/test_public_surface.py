import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_public_surface_contract_is_versioned_and_complete() -> None:
    contract = json.loads((ROOT / "contracts/public_surface.json").read_text(encoding="utf-8"))
    assert contract["schema_version"] == 1
    assert set(contract) == {
        "schema_version",
        "cli_commands",
        "mcp_tools",
        "sdk_exports",
        "documentation",
        "first_class_integrations",
        "supported_example_integrations",
        "optional_extras",
    }
    for key in set(contract) - {"schema_version"}:
        assert len(contract[key]) == len(set(contract[key]))


def test_public_surface_has_only_canonical_integration_entrypoints() -> None:
    contract = json.loads((ROOT / "contracts/public_surface.json").read_text(encoding="utf-8"))
    removed = {"wire", "wire_project", "bootstrap_project", "plan_integration"}
    assert "integrate" in contract["cli_commands"]
    assert "integrate_project" in contract["mcp_tools"]
    assert removed.isdisjoint(contract["cli_commands"] + contract["mcp_tools"] + contract["sdk_exports"])
