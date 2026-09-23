"""The reviewer's edits to a static integration plan, as data.

A fixture's ``expected.json`` may carry ``plan_overrides`` modelling the review an agent performs
on the planner's proposal before re-planning: operators it removes (helpers, the entrypoint
wrapper), operators it renames or re-parents, the scenarios it declares (one per route, each with
a command), and the entrypoint it keeps. ``apply_plan_overrides`` applies them to the saved plan
JSON; ``retobs integrate . --phase plan --plan <file>`` then regenerates the patches from it.
"""
from __future__ import annotations

import json
from typing import Any


def apply_plan_overrides(plan_payload: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``plan_payload`` (a saved plan result, or a bare plan) with the review applied."""
    payload = json.loads(json.dumps(plan_payload))
    plan = payload.get("plan", payload)
    removed = set(overrides.get("remove_operators", ()))
    edits = overrides.get("operators", {})
    renamed = {planned: edit["op_id"] for planned, edit in edits.items() if "op_id" in edit}
    plan["operators"] = [
        {**operator, **edits.get(operator["op_id"], {})}
        for operator in plan["operators"]
        if operator["op_id"] not in removed
    ]
    # The planner keeps reviewed scenarios verbatim, so they must not expect a removed operator.
    plan["scenarios"] = [
        {
            **scenario,
            "expected_operator_ids": [renamed.get(op, op) for op in scenario["expected_operator_ids"] if op not in removed],
            "expected_edges": [
                [renamed.get(parent, parent), renamed.get(child, child)]
                for parent, child in scenario.get("expected_edges", [])
                if parent not in removed and child not in removed
            ],
        }
        for scenario in plan["scenarios"]
    ]
    if "scenarios" in overrides:
        plan["scenarios"] = [dict(scenario) for scenario in overrides["scenarios"]]
    if "entrypoint" in overrides:
        plan.setdefault("discovery", {})["entrypoint"] = dict(overrides["entrypoint"])
    return payload
