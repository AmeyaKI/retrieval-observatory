from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from retrieval_observatory.tracing.model import RetrievalTrace


@dataclass(frozen=True)
class CandidateEvent:
    op_id: str
    op_type: str
    state: Literal["input", "emitted", "removed", "absent", "skipped", "unknown"]
    input_parents: tuple[str, ...] = ()
    rank: int | None = None
    score: float | None = None
    drop_reason: str | None = None


@dataclass(frozen=True)
class CandidateHistoryIndex:
    by_document: Mapping[str, tuple[CandidateEvent, ...]]
    complete: bool
    limitations: tuple[str, ...]

    @classmethod
    def build(cls, trace: RetrievalTrace) -> "CandidateHistoryIndex":
        document_ids = {
            candidate.doc_id
            for span in trace.spans
            for group in (*span.input_groups.values(), span.outputs)
            for candidate in group
        }
        histories: dict[str, list[CandidateEvent]] = {doc_id: [] for doc_id in document_ids}
        limitations: list[str] = []
        if trace.capture.candidates_truncated:
            limitations.append("candidate_payload_truncated")
        if not trace.capture.sampled:
            limitations.append("trace_not_sampled")
        for span in trace.spans:
            if span.status == "SKIPPED_BY_GATE":
                for doc_id in document_ids:
                    histories[doc_id].append(CandidateEvent(span.op_id, span.op_type, "skipped"))
                continue
            inputs = {
                candidate.doc_id: (parent_id, candidate)
                for parent_id, candidates in span.input_groups.items()
                for candidate in candidates
            }
            outputs = {candidate.doc_id: candidate for candidate in span.outputs}
            if span.status == "FIRED" and span.parent_ids and not span.input_groups:
                limitations.append(f"missing_inputs:{span.op_id}")
            for doc_id in document_ids:
                parents = tuple(parent for parent, candidates in span.input_groups.items() if any(c.doc_id == doc_id for c in candidates))
                if doc_id in outputs:
                    candidate = outputs[doc_id]
                    state = "emitted"
                elif doc_id in inputs:
                    candidate = inputs[doc_id][1]
                    state = "removed"
                else:
                    candidate = None
                    state = "absent"
                histories[doc_id].append(CandidateEvent(
                    span.op_id, span.op_type, state, parents,
                    candidate.rank if candidate else None,
                    candidate.score if candidate else None,
                    candidate.drop_reason if candidate else None,
                ))
        unique_limitations = tuple(dict.fromkeys(limitations))
        return cls({key: tuple(value) for key, value in histories.items()}, not unique_limitations, unique_limitations)

    def for_document(self, doc_id: str) -> tuple[CandidateEvent, ...]:
        return self.by_document.get(doc_id, ())
