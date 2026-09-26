"""Never-registered Typer groups and their commands are gone; the registered ones remain."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from retrieval_observatory import cli

REMOVED = (
    "classifier_app", "forge_app", "tracelens_app", "advisor_app", "golden_app",
    "diagram", "_diagram", "classifier_train", "_classifier_train", "classifier_predict", "classifier_report",
    "_print_classifier_report", "advisor_check", "_advisor_check", "advisor_recommend_cmd", "_advisor_recommend",
    "golden_run", "_golden_run", "golden_list", "_golden_list", "golden_create", "_golden_create", "_open_store",
    "_forge_deprecated", "_tracelens_deprecated",
    "testsets_app", "production_app", "forge_scan", "forge_run", "forge_list", "tracelens_demo", "tracelens_stats",
    "tracelens_purge", "quickstart", "_seed_showcase_traces", "_build_demo_queries",
)


@pytest.mark.parametrize("name", REMOVED)
def test_dead_cli_symbol_is_gone(name: str) -> None:
    assert not hasattr(cli, name)


@pytest.mark.parametrize("command", ["diagram", "classifier", "forge", "tracelens", "advisor", "golden", "testsets", "production"])
def test_dead_command_is_unknown(command: str) -> None:
    result = CliRunner().invoke(cli.app, [command, "--help"])
    assert result.exit_code != 0 and "No such command" in result.output


@pytest.mark.parametrize("command", [["mcp", "init"], ["storage", "index"], ["demo"]])
def test_live_groups_still_answer(command: list[str]) -> None:
    result = CliRunner().invoke(cli.app, [*command, "--help"])
    assert result.exit_code == 0, result.output
