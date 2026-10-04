"""Build the integration plan from what a watched search actually ran (``--watch``)."""
from __future__ import annotations

import json
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


def _reader(base: str, slot: str) -> str:
    """``base`` read at one bundle slot: ``index:0`` → ``[0]``, ``key:x`` → ``["x"]``, ``attr:documents`` → ``.documents``."""
    kind, _, name = slot.partition(":")
    return base + {"index": f"[{name}]", "key": f"[{json.dumps(name)}]", "attr": f".{name}"}[kind]


def _argument(param: str) -> str:
    """How a ``CaptureSpec.inputs`` callable reads one watched input: ``hits`` or ``lanes[index:0]``."""
    name, _, slot = param.partition("[")
    base = f"bound.arguments[{json.dumps(name)}]"
    return _reader(base, slot[:-1]) if slot else base


def _capture_question(step: WatchedStep) -> str | None:
    """A ready ``CaptureSpec`` for a step whose documents the default capture cannot read exactly: a
    bundle return, inputs inside a bundle argument, or several parents in parameters not named after them."""
    parts: list[str] = []
    said: list[str] = []
    if any("[" in param for param, _parent in step.inputs_from) or (
        len(step.parent_ids) > 1 and any(param != parent for param, parent in step.inputs_from)
    ):
        groups = ", ".join(f"{json.dumps(parent)}: {_argument(param)}" for param, parent in step.inputs_from)
        parts.append(f"inputs=lambda bound: {{{groups}}}")
        said.append("its parents' documents arrive as " + ", ".join(f"{param} from {parent}" for param, parent in step.inputs_from))
    if step.output_bundle:
        parts.append(f"outputs=lambda result: {_reader('result', step.output_bundle)}")
        said.append(f"it returns a bundle; its documents are {step.output_bundle}")
    if not parts:
        return None
    name = f"{step.op_id}_capture"
    return (
        f"operator {step.op_id}: {' and '.join(said)}: add to retobs_adapter.py `{name} = CaptureSpec({', '.join(parts)})`, "
        f"set the operator's capture to \"retobs_adapter:{name}\", and plan again from the reviewed plan"
    )


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
    # A name match that ran inside a watched step (it worked on documents that step made) did run.
    folded_into = {key: step.op_id for step in watch.steps for key in step.inside_keys}
    not_seen = [
        {"symbol": op.symbol, "relative_path": op.relative_path, "op_type": op.op_type, "confidence": op.confidence,
         **({"reason": "folded_into_step", "step": folded_into[key]} if key in folded_into else {"reason": "not_seen_in_watch"})}
        for op in guessed.operators if (key := (op.relative_path, op.symbol)) not in watched
    ]
    capture_questions = [question for step in watch.steps if (question := _capture_question(step))]
    questions.extend(capture_questions)
    questions.extend(f"watched step {item['symbol']} ({item['relative_path']}): {item['reason']}" for item in watch.unmarkable)
    placeholder = [scenario.scenario_id for scenario in plan.scenarios if scenario.query_text == SCENARIO_QUERY_TEXT]
    if placeholder:
        questions.append(
            f"scenario query_text is the placeholder {SCENARIO_QUERY_TEXT!r} for {', '.join(placeholder)}: the watched entrypoint "
            "received no query-named argument (query, q, question, text); set each to the question its command searches for"
        )
    expected = dict(plan.expected_capabilities)
    # Until the agent adds those CaptureSpecs, the default capture reads those steps inexactly.
    if capture_questions and expected.get("actual_input_output_capture") == "ready":
        expected["actual_input_output_capture"] = "partial"
    discovery = {
        **plan.discovery, "method": "watched", "watch": watch.to_dict(),
        "low_confidence_operators": [*guessed.discovery.get("low_confidence_operators", ()), *not_seen],
    }
    return _recreate(plan, discovery=discovery, expected_capabilities=expected, open_questions=(*plan.open_questions, *questions))
