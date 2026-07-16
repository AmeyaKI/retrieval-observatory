from __future__ import annotations

import argparse
import json
from pathlib import Path

import retrieval_observatory as ro
from retrieval_observatory.cli import app
from retrieval_observatory.mcp.server import build_server

ROOT = Path(__file__).resolve().parents[1]


def actual_surface() -> dict[str, list[str]]:
    cli = {command.name for command in app.registered_commands if command.name}
    cli.update(group.name for group in app.registered_groups if group.name and not group.hidden)
    server = build_server()
    manager = server._tool_manager
    tools = manager.list_tools()
    if hasattr(tools, "__await__"):
        import asyncio

        tools = asyncio.run(tools)
    return {
        "cli_commands": sorted(cli),
        "mcp_tools": sorted(tool.name for tool in tools),
        "sdk_exports": sorted(ro.__all__),
    }


def validate_surface() -> dict[str, dict[str, list[str]]]:
    expected = json.loads((ROOT / "contracts/public_surface.json").read_text(encoding="utf-8"))
    actual = actual_surface()
    return {
        key: {"expected": sorted(expected[key]), "actual": actual[key]}
        for key in actual
        if sorted(expected[key]) != actual[key]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    mismatches = validate_surface()
    if args.json:
        print(json.dumps({"valid": not mismatches, "mismatches": mismatches}, indent=2, sort_keys=True))
    elif mismatches:
        for key, values in mismatches.items():
            print(f"{key}: expected {values['expected']}; actual {values['actual']}")
    else:
        print("Public surface matches contracts/public_surface.json.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
