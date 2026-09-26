"""Capture specs the reviewed plan references (root-level ``retobs_adapter.py``).

``rrf_fusion(*lanes)`` takes its lanes positionally, which the default capture rules can only
match by position; this spec reads each lane from the bound arguments and names its producer.
"""
from __future__ import annotations

from inspect import BoundArguments
from typing import Any, Mapping, Sequence

from retrieval_observatory.tracing.capture import CaptureSpec

#: The pipeline passes the lexical lane first and, on the hybrid route only, the dense lane second.
LANE_PRODUCERS = ("lexical", "dense")


def _lanes_by_producer(bound: BoundArguments | None) -> Mapping[str, Sequence[Any]] | None:
    if bound is None:
        return None
    lanes = bound.arguments.get("lanes") or ()
    return {producer: list(lane) for producer, lane in zip(LANE_PRODUCERS, lanes)}


rrf_fusion_capture = CaptureSpec(inputs=_lanes_by_producer)
