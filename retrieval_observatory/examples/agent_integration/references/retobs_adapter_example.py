"""Project-local capture specs for retobs (place this file at the project root as ``retobs_adapter.py``).

Reference each spec from the plan with ``"capture": "retobs_adapter:<symbol>"``. Everything here is
observational: read the bound arguments and the returned object, return candidate sequences, never
mutate application objects, and never consume an iterator the application still needs.
"""
from __future__ import annotations

from inspect import BoundArguments
from typing import Any, Mapping, Sequence

from retrieval_observatory.tracing.capture import CaptureSpec


def _rerank_inputs(bound: BoundArguments | None) -> Mapping[str, Sequence[Any]] | None:
    """The reranker receives candidates inside a request object; expose them per parent operator."""
    if bound is None:
        return None
    request = bound.arguments.get("request")
    if request is None:
        return None
    # Key by the parent op_id declared in the plan; the values are the actual candidate objects.
    return {"rrf_fusion": list(request.candidates)}


def _rerank_outputs(result: Any) -> Sequence[Any] | None:
    """The reranker returns a response object; its ``.ranked`` list is the candidate output."""
    ranked = getattr(result, "ranked", None)
    return list(ranked) if ranked is not None else None


rerank_capture = CaptureSpec(inputs=_rerank_inputs, outputs=_rerank_outputs)


def _fusion_inputs(bound: BoundArguments | None) -> Mapping[str, Sequence[Any]] | None:
    """A fuser taking ``{lane_name: candidates}`` maps each lane to the parent that produced it."""
    if bound is None:
        return None
    lanes = bound.arguments.get("lanes") or {}
    parents = {"lexical": "bm25", "semantic": "dense"}
    return {parents[name]: list(items) for name, items in lanes.items() if name in parents}


def _fusion_decisions(bound: BoundArguments | None, result: Any) -> Mapping[str, Any]:
    """Optional: a per-candidate reason retobs shows next to the transition (recorded, not inferred)."""
    return {str(item["id"]): "fused" for item in result}


fusion_capture = CaptureSpec(inputs=_fusion_inputs, decisions=_fusion_decisions)
