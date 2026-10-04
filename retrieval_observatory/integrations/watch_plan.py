"""Build the integration plan from what a watched search actually ran (``--watch``)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from retrieval_observatory.integrations.model import IntegrationPlan, OperatorMapping, VerificationScenario
from retrieval_observatory.integrations.planner import SCENARIO_QUERY_TEXT, build_integration_plan
from retrieval_observatory.integrations.watch_map import WatchedStep, WatchMap


def _operator(step: WatchedStep, guessed: dict[tuple[str, str], str]) -> OperatorMapping:
    # A GATE returns a route, not documents: it has no counts.
    counts = [] if step.op_type == "GATE" else [f"watched: took {step.took}, returned {step.returned}"]
    notes = [*counts, *step.notes]
    if step.inside:
        notes.append("inside: " + "; ".join(step.inside))
    if step.inputs_from:
        notes.append("inputs: " + ", ".join(f"{param} from {parent}" for param, parent in step.inputs_from))
    op_type = step.op_type or guessed.get((step.relative_path, step.symbol)) or "FILTER"
    if step.op_type is None:
        notes.append(f"kind {op_type} taken from {'the name' if (step.relative_path, step.symbol) in guessed else 'the default'}: confirm it")
    return OperatorMapping(
        op_id=step.op_id, op_type=op_type, symbol=step.symbol, relative_path=step.relative_path,
        parent_ids=step.parent_ids, confidence=1.0, invocation="async" if step.invocation == "async" else "sync",
        notes="; ".join(notes),
    )


def _scenarios(watch: WatchMap) -> tuple[VerificationScenario, ...]:
    """One scenario per watched command that ran a search (its command and query), plus a repeat of the first."""
    searched = sorted({index for step in watch.steps for index in step.commands})
    scenarios: list[VerificationScenario] = []
    for position, index in enumerate(searched):
        route = (watch.chooser or {}).get("values", {}).get(str(index))
        expected = tuple(step.op_id for step in watch.steps if index in step.commands)
        scenario_id = "representative" if position == 0 else f"watched-{index + 1}"
        scenarios.append(VerificationScenario(scenario_id, watch.query_texts[index] or SCENARIO_QUERY_TEXT, expected,
                                              command=watch.commands[index], route=route))
    if scenarios:
        scenarios.append(replace(scenarios[0], scenario_id="representative-repeat"))
    return tuple(scenarios)


def _recreate(plan: IntegrationPlan, **changes: Any) -> IntegrationPlan:
    """``plan`` with ``changes``, through ``IntegrationPlan.create`` so ``plan_id`` covers them."""
    fields = dict(
        project_root=Path(plan.project_root), framework=plan.framework, service_id=plan.service_id,
        pipeline_id=plan.pipeline_id, patches=plan.patches, operators=plan.operators,
        candidate_mapping=plan.candidate_mapping, scenarios=plan.scenarios, unresolved=plan.unresolved,
        discovery=plan.discovery, boundary=plan.boundary, identity=plan.identity, judgments=plan.judgments,
        expected_capabilities=plan.expected_capabilities, actions=plan.actions, open_questions=plan.open_questions,
        notes=plan.notes,
    )
    fields.update(changes)
    return IntegrationPlan.create(**fields)


def build_watched_plan(
    project_root: Path, watch: WatchMap, framework: str | None = None, *,
    db_path: str = ".retobs/results.db", failures: Sequence[str] = (),
) -> IntegrationPlan:
    """The plan from a watched search. With no watched step, the name-guessed plan, saying why."""
    root = project_root.resolve()
    guessed = build_integration_plan(root, framework, db_path=db_path)
    questions = [f"watch: {failure}" for failure in failures]
    if not watch.steps:
        reason = "no watched command ran a search that handed back documents"
        discovery = {**guessed.discovery, "method": "guessed", "watch": watch.to_dict(), "watch_fallback_reason": reason}
        return _recreate(guessed, discovery=discovery, open_questions=(
            *guessed.open_questions, *questions, f"steps were guessed from names because {reason}; fix the --watch command and plan again",
        ))
    guessed_types = {(op.relative_path, op.symbol): op.op_type for op in guessed.operators}
    for item in guessed.discovery.get("low_confidence_operators", ()):
        guessed_types.setdefault((item["relative_path"], item["symbol"]), item["op_type"])
    entrypoint = dict(watch.entrypoint) if watch.entrypoint else guessed.discovery.get("entrypoint")
    if watch.entrypoint is None:
        current = f"is the name-guessed {entrypoint['symbol']} ({entrypoint['file']})" if entrypoint else "is not set"
        questions.append(
            f"the watched search starts in a function that cannot carry a decorator (see discovery.watch.notes); "
            f"discovery.entrypoint {current}: set it to the function the search enters"
        )
    identity = replace(guessed.identity, query_text_parameter=watch.query_parameter) if watch.query_parameter else guessed.identity
    reviewed = replace(
        guessed, operators=tuple(_operator(step, guessed_types) for step in watch.steps), scenarios=_scenarios(watch),
        identity=identity, discovery={**guessed.discovery, "entrypoint": entrypoint},
    )
    plan = build_integration_plan(root, framework, db_path=db_path, reviewed=reviewed)
    watched = {(step.relative_path, step.symbol) for step in watch.steps}
    not_seen = [
        {"symbol": op.symbol, "relative_path": op.relative_path, "op_type": op.op_type, "confidence": op.confidence, "reason": "not_seen_in_watch"}
        for op in guessed.operators if (op.relative_path, op.symbol) not in watched
    ]
    readers = {"index": "result[{}]", "key": "result[{!r}]", "attr": "result.{}"}
    for step in watch.steps:
        if step.output_bundle:
            name = f"{step.op_id}_capture"
            kind, _, slot = step.output_bundle.partition(":")
            expression = readers[kind].format(int(slot) if kind == "index" else slot)
            questions.append(
                f"operator {step.op_id} returns a bundle; its documents are {step.output_bundle}: add to retobs_adapter.py "
                f"`{name} = CaptureSpec(outputs=lambda result: {expression})`, set the operator's capture to "
                f"\"retobs_adapter:{name}\", and plan again from the reviewed plan"
            )
    questions.extend(f"watched step {item['symbol']} ({item['relative_path']}): {item['reason']}" for item in watch.unmarkable)
    discovery = {
        **plan.discovery, "method": "watched", "watch": watch.to_dict(),
        "low_confidence_operators": [*guessed.discovery.get("low_confidence_operators", ()), *not_seen],
    }
    return _recreate(plan, discovery=discovery, open_questions=(*plan.open_questions, *questions))
