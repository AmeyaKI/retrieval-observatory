#!/usr/bin/env python3
"""The flagship demo's multi-stage retrieval DAG, built on retobs' operator graph.

Eleven operators, two routing decisions, two parallel search lanes:

    bm25_lane   dense_lane          depth 0   keyword + vector search, top `lane_depth` each
         └────┬────┘
        hybrid_fusion               depth 1   reciprocal rank fusion
             │
         type_gate                  depth 2   GATE — HotpotQA's own bridge/comparison label
          ┌──┴───┐
  bridge_hop2   comparison_widen    depth 3   EXPAND
       │            │
 bridge_siblings    │               depth 4   EXPAND
       └────┬───────┘
        route_merge                 depth 5   FUSE
             │
      confidence_gate               depth 6   GATE — did the two lanes agree?
        ┌────┴────┐
   fast_lane    rerank              depth 7   passthrough | cross-encoder
        └────┬────┘
     final_selection                depth 8   FUSE -> top `final_k`   <- policy watches this

Both routing decisions are deterministic. Neither uses a trained model, and neither reads
ground truth: `type` is an input attribute of the question, and lane agreement is computed
from retrieval scores the pipeline already produced.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from retrieval_observatory.adapters.bm25_adapter import BM25Adapter
from retrieval_observatory.adapters.hf_adapter import HFCrossEncoderAdapter
from retrieval_observatory.adapters.hf_biencoder_adapter import HFBiEncoderAdapter
from retrieval_observatory.config.operators import (
    ExpandSpec,
    FuseSpec,
    GateSpec,
    PipelineGraphSpec,
    RerankSpec,
    SourceSpec,
    TransformSpec,
)
from retrieval_observatory.config.schema import (
    DatasetConfig,
    ExecutionConfig,
    ExperimentConfig,
    ExperimentMeta,
    GraphNodeConfig,
    GraphPipelineConfig,
    MetricsConfig,
    ReleaseIdentityConfig,
)
from retrieval_observatory.pipeline.dag import DAGPipeline
from retrieval_observatory.types import Document, Query, RetrievalResult

PIPELINE_ID = "hotpotqa_hybrid_dag"

#: How the corpus is turned into indexable text. Recorded as `chunking_revision`, so a change
#: here is visible to retobs' comparability check instead of silently shifting the numbers.
CHUNKING_REVISION = "title-prefixed-paragraph-v1"


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineSettings:
    """Every knob the demo exposes. Scenario variants are `dataclasses.replace` of this."""

    # Widths are sized for a legible demo, not for peak retrieval accuracy. Every candidate
    # is recorded at both ends of every operator it passes, so these values set the stored
    # trace size (~0.6 KB per candidate slot per query) as much as they set quality.
    lane_depth: int = 30           # candidates each search lane returns
    rrf_k: int = 60                # reciprocal-rank-fusion constant
    fusion_top_k: int = 40         # candidates surviving the hybrid merge
    bridge_hop2_depth: int = 25    # candidates the second-hop re-search returns per lane
    sibling_limit: int = 10        # paragraphs the link expansion may add
    sibling_source_docs: int = 3   # how many top candidates are scanned for outgoing links
    widen_depth: int = 60          # candidates the comparison lane re-searches to
    rerank_candidates: int = 40    # candidates handed to the cross-encoder
    final_k: int = 10              # final result size

    bm25_lane_enabled: bool = True
    dense_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    #: Encode queries with this model while leaving the index built by `dense_model`.
    #: Reproduces the stale-index mistake: the embedding model was swapped, the index was
    #: not rebuilt. Both models emit 384 dimensions, so nothing errors — the vectors are
    #: simply from two unrelated spaces and similarity becomes close to noise.
    stale_query_encoder: str | None = None

    #: The lane-agreement test assumes exactly two search lanes; with three, the score
    #: arithmetic below stops being a proof.
    LANE_COUNT = 2

    @property
    def agreement_threshold(self) -> float:
        """A fused top score above this proves both lanes ranked the same document *first*.

        Fusion gives a document ``1 / (rrf_k + rank)`` from each lane that found it, summed.
        So:

          * unanimous first place scores exactly ``2 / (rrf_k + 1)``
          * the best any other document can reach is first in one lane and second in the
            other: ``1 / (rrf_k + 1) + 1 / (rrf_k + 2)`` — strictly less

        The threshold sits midway between those two values, so the comparison is exact
        arithmetic rather than a tuned cutoff, and it does not depend on how deep the lanes
        search. An earlier version of this rule tested only whether the top document was
        found by *both* lanes; that turned out to be true 100% of the time, because fusion
        structurally ranks any two-lane document above any one-lane document.
        """
        unanimous = 2.0 / (self.rrf_k + 1)
        best_without_unanimity = 1.0 / (self.rrf_k + 1) + 1.0 / (self.rrf_k + 2)
        return (unanimous + best_without_unanimity) / 2.0


# --------------------------------------------------------------------------------------
# Corpus loading
# --------------------------------------------------------------------------------------


@dataclass
class DemoCorpus:
    index_text: dict[str, str]   # doc_id -> text actually indexed (title-prefixed)
    titles: dict[str, str]       # doc_id -> paragraph title
    fingerprint: str             # sha256 of corpus.jsonl, from the dataset manifest

    @classmethod
    def load(cls, data_dir: Path) -> "DemoCorpus":
        index_text: dict[str, str] = {}
        titles: dict[str, str] = {}
        with (data_dir / "corpus.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                doc_id, title = row["id"], row["title"]
                titles[doc_id] = title
                # Title-prefixed: HotpotQA answers hinge on which *article* a paragraph is
                # from, and the title is often the only place the subject is named outright.
                index_text[doc_id] = f"{title}. {row['text']}"
        manifest = json.loads((data_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
        return cls(index_text, titles, manifest["fingerprints"]["corpus.jsonl"])


# --------------------------------------------------------------------------------------
# Link index — which corpus paragraphs does this paragraph name?
# --------------------------------------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9]+")


class TitleMentionIndex:
    """Finds corpus paragraphs whose title is named verbatim inside a piece of text.

    HotpotQA ships no hyperlink graph, so the demo derives one from the corpus itself: a
    Wikipedia opening paragraph usually names the other articles it relates to. Matching is
    on lowercased alphanumeric token sequences, so punctuation and casing don't block a hit.

    Built from the corpus only. It never reads a question's bundled paragraphs, so it cannot
    leak which documents are the gold ones.
    """

    def __init__(self, titles: dict[str, str]):
        self._by_first_token: dict[str, list[tuple[tuple[str, ...], str]]] = {}
        for doc_id, title in titles.items():
            tokens = tuple(_TOKEN.findall(title.lower()))
            if not tokens:
                continue
            self._by_first_token.setdefault(tokens[0], []).append((tokens, doc_id))

    def mentioned_in(self, text: str) -> list[str]:
        """Document ids whose title appears as a token sequence in `text`, in order of first
        appearance."""
        tokens = _TOKEN.findall(text.lower())
        found: list[str] = []
        seen: set[str] = set()
        for position, token in enumerate(tokens):
            for title_tokens, doc_id in self._by_first_token.get(token, ()):
                end = position + len(title_tokens)
                if end <= len(tokens) and tuple(tokens[position:end]) == title_tokens:
                    if doc_id not in seen:
                        seen.add(doc_id)
                        found.append(doc_id)
        return found


# --------------------------------------------------------------------------------------
# Retrieval lanes
# --------------------------------------------------------------------------------------


class FixedDepthLane:
    """Runs a retrieval adapter at a fixed candidate depth and carries text through the graph.

    Two jobs:

    * **Depth.** Lanes must fetch deeper than the pipeline returns — fusion and reranking
      need something to work with. ``Query.k`` carries the *final* result size, so each lane
      overrides it.
    * **Payload.** retobs' operator graph passes candidates between stages, and a candidate
      carries its ``metadata`` dict but not a document ``text`` attribute. Every downstream
      executor rebuilds documents with ``text=metadata["text"]``, so a lane that returns text
      only as an attribute hands empty strings to every later stage — which silently turns
      the reranker into a no-op (it scores identical empty strings) and leaves the link
      expansion nothing to scan.

      Putting the *whole* paragraph in metadata fixes that, but every candidate is recorded
      in the trace at both ends of every operator it passes through, so full text inflates
      the stored trace roughly two-and-a-half fold. Instead the lane attaches a short preview
      — enough for the dashboard's lineage view to be readable — and the two operators that
      genuinely need the full paragraph re-read it from the corpus by document id.
    """

    supports_filters = False

    #: Characters of paragraph text carried in the trace, for display only.
    PREVIEW_CHARS = 160

    def __init__(self, adapter: Any, depth: int, retriever_id: str, titles: dict[str, str]):
        self._adapter = adapter
        self._depth = depth
        self._titles = titles
        self.retriever_id = retriever_id

    async def retrieve(self, query: Query) -> RetrievalResult:
        result = await _await_maybe(self._adapter.retrieve(dataclasses.replace(query, k=self._depth)))
        result.documents = [
            dataclasses.replace(
                document,
                title=self._titles.get(document.id, ""),
                metadata={
                    **document.metadata,
                    "title": self._titles.get(document.id, ""),
                    "preview": document.text[: self.PREVIEW_CHARS],
                    "found_by": self.retriever_id,
                },
            )
            for document in result.documents
        ]
        return result


class StaleIndexVectorLane:
    """A vector index left over from the previous embedding model.

    The index is built by `index_model`; queries are then encoded by `query_model`. Nothing
    raises — both models emit 384-dimensional vectors, so the search runs happily and returns
    documents ranked by similarity between two unrelated embedding spaces. This is what
    "swapped the model, forgot to rebuild the index" actually looks like in production: no
    error, no warning, just quietly meaningless retrieval.
    """

    supports_filters = False

    def __init__(self, corpus: dict[str, str], index_model: str, query_model: str, retriever_id: str):
        self._adapter = HFBiEncoderAdapter(corpus, model_name=index_model, retriever_id=retriever_id)
        self._query_model = query_model
        self._swapped = False
        self.retriever_id = retriever_id

    def _ensure_stale(self) -> None:
        if self._swapped:
            return
        from sentence_transformers import SentenceTransformer

        # Build (or load) the index under the ORIGINAL model first, then replace only the
        # query encoder. Order matters: _build_index also sets the adapter's encoder.
        if self._adapter._index is None:
            self._adapter._build_index()
        self._adapter._model = SentenceTransformer(self._query_model)
        self._swapped = True

    async def retrieve(self, query: Query) -> RetrievalResult:
        self._ensure_stale()
        return await self._adapter.retrieve(query)


class CorpusReranker:
    """Cross-encoder reranking, with paragraph text re-read from the corpus at scoring time.

    Candidates arriving here carry only a preview (see :class:`FixedDepthLane`), so the full
    paragraph is looked up by document id before scoring. Scoring truncated previews instead
    would quietly degrade the reranker rather than fail.
    """

    def __init__(self, model_name: str, index_text: dict[str, str], retriever_id: str = "cross_encoder"):
        self.retriever_id = retriever_id
        self._adapter = HFCrossEncoderAdapter(model_name, retriever_id=retriever_id)
        self._index_text = index_text

    async def rerank(self, query: Query, documents: Sequence[Document]) -> RetrievalResult:
        hydrated = [
            dataclasses.replace(document, text=self._index_text.get(document.id, document.text))
            for document in documents
        ]
        return await self._adapter.rerank(query, hydrated)


class DisabledLane:
    """A retrieval lane that is switched off: it still runs, and returns nothing.

    Used by the regression scenario. Deleting the operator instead would change the graph's
    shape, which changes how retobs names each stage's measurements — the release policy's
    guard would then point at a measurement that exists in one run and not the other, and the
    comparison would fail for a bookkeeping reason rather than a quality one.
    """

    supports_filters = False

    def __init__(self, retriever_id: str):
        self.retriever_id = retriever_id

    async def retrieve(self, query: Query) -> RetrievalResult:
        return RetrievalResult(documents=[], latency_ms=0.0, retriever_id=self.retriever_id)


# --------------------------------------------------------------------------------------
# Candidate helpers
# --------------------------------------------------------------------------------------


def _renumber(documents: Iterable[Document]) -> list[Document]:
    """Return documents renumbered 1..N, dropping any repeated document id.

    Every operator output must have unique candidate ids or retobs rejects the trace — an
    expansion step that re-adds a document already in the list is the easy way to trip this.
    """
    output: list[Document] = []
    seen: set[str] = set()
    for document in documents:
        if document.id in seen:
            continue
        seen.add(document.id)
        output.append(dataclasses.replace(document, rank=len(output) + 1))
    return output


def _stamp_agreement(documents: Sequence[Document], settings: PipelineSettings) -> list[Document]:
    """Record whether both search lanes independently ranked the same document first.

    Computed here, at the first operator downstream of the hybrid merge, because this is the
    last point where the fused scores are intact — later merge steps recompute scores from
    ranks and the evidence is gone. The verdict is stamped onto every candidate so the
    confidence gate can read it after the branches rejoin.
    """
    agreed = bool(documents) and documents[0].score > settings.agreement_threshold
    return [
        dataclasses.replace(document, metadata={**document.metadata, "lanes_agree": agreed})
        for document in documents
    ]


async def _await_maybe(value: Any) -> Any:
    return await value if asyncio.iscoroutine(value) else value


async def _search_both_lanes(lanes: Sequence[Any], text: str, depth: int, template: Query) -> list[Document]:
    query = dataclasses.replace(template, text=text, k=depth)
    results = await asyncio.gather(*[_await_maybe(lane.retrieve(query)) for lane in lanes])
    return [document for result in results for document in result.documents]


# --------------------------------------------------------------------------------------
# Operators
# --------------------------------------------------------------------------------------


def _question_type_router(query: Query, documents: Sequence[Document]) -> str:
    """Bridge questions need a second hop; comparison questions name both subjects already."""
    return "comparison" if query.metadata.get("type") == "comparison" else "bridge"


def _confidence_router(query: Query, documents: Sequence[Document]) -> str:
    """Rerank only when the two search lanes disagreed about which document is best.

    Spending the expensive stage where retrieval is already unanimous buys little; spending
    it where two independently-failing methods disagree is where a stronger model earns its
    place. On this dataset the split is close to even.
    """
    return "agree" if documents and documents[0].metadata.get("lanes_agree") else "disagree"


def _make_bridge_hop2(lanes, settings: PipelineSettings, titles: dict[str, str]):
    """Second hop: re-search using the entity named by the current best candidate.

    A bridge question ("what position was held by the woman who played X") cannot be answered
    by one search — the first pass finds who that person is, and the second pass searches
    again with their name attached.
    """

    async def expand(query: Query, documents: Sequence[Document]) -> list[Document]:
        documents = _stamp_agreement(documents, settings)
        if not documents:
            return []
        bridge_entity = titles.get(documents[0].id, "")
        if not bridge_entity:
            return _renumber(documents)
        second_hop = await _search_both_lanes(
            lanes, f"{query.text} {bridge_entity}", settings.bridge_hop2_depth, query
        )
        carried = {"lanes_agree": documents[0].metadata.get("lanes_agree")}
        added = [
            dataclasses.replace(document, metadata={**document.metadata, **carried, "added_by": "bridge_hop2"})
            for document in second_hop
        ]
        return _renumber([*documents, *added])

    return expand


def _make_bridge_siblings(index: TitleMentionIndex, corpus: DemoCorpus, settings: PipelineSettings):
    """Link expansion: pull in paragraphs that the best candidates name outright."""

    async def expand(query: Query, documents: Sequence[Document]) -> list[Document]:
        if not documents:
            return []
        present = {document.id for document in documents}
        carried = {"lanes_agree": documents[0].metadata.get("lanes_agree")}
        added: list[Document] = []
        for document in documents[: settings.sibling_source_docs]:
            # Full paragraph re-read from the corpus: candidates only carry a preview.
            for doc_id in index.mentioned_in(corpus.index_text.get(document.id, "")):
                if doc_id in present or len(added) >= settings.sibling_limit:
                    continue
                present.add(doc_id)
                added.append(
                    Document(
                        id=doc_id,
                        text=corpus.index_text[doc_id],
                        score=0.0,
                        rank=len(documents) + len(added) + 1,
                        title=corpus.titles[doc_id],
                        metadata={
                            **carried,
                            "title": corpus.titles[doc_id],
                            "preview": corpus.index_text[doc_id][: FixedDepthLane.PREVIEW_CHARS],
                            "added_by": "bridge_siblings",
                            "linked_from": document.id,
                        },
                    )
                )
            if len(added) >= settings.sibling_limit:
                break
        return _renumber([*documents, *added])

    return expand


def _make_comparison_widen(lanes, settings: PipelineSettings):
    """Single wider pass: both subjects are named in the question, so go deeper, not twice."""

    async def expand(query: Query, documents: Sequence[Document]) -> list[Document]:
        documents = _stamp_agreement(documents, settings)
        widened = await _search_both_lanes(lanes, query.text, settings.widen_depth, query)
        carried = {"lanes_agree": documents[0].metadata.get("lanes_agree") if documents else False}
        added = [
            dataclasses.replace(document, metadata={**document.metadata, **carried, "added_by": "comparison_widen"})
            for document in widened
        ]
        return _renumber([*documents, *added])

    return expand


async def _fast_lane(query: Query, documents: Sequence[Document]) -> list[Document]:
    """No-op: the lanes agreed, so the fused order is taken as-is and reranking is skipped."""
    return _renumber(documents)


# --------------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------------


def _graph() -> PipelineGraphSpec:
    return PipelineGraphSpec(
        PIPELINE_ID,
        (
            SourceSpec("bm25_lane", (), adapter="bm25_lane"),
            SourceSpec("dense_lane", (), adapter="dense_lane"),
            FuseSpec("hybrid_fusion", ("bm25_lane", "dense_lane"), params={"rrf_k": 60}, top_k=60),
            GateSpec(
                "type_gate",
                ("hybrid_fusion",),
                router="type_router",
                branches={
                    "bridge": ("bridge_hop2", "bridge_siblings"),
                    "comparison": ("comparison_widen",),
                },
            ),
            ExpandSpec("bridge_hop2", ("type_gate",), expander="bridge_hop2"),
            ExpandSpec("bridge_siblings", ("bridge_hop2",), expander="bridge_siblings"),
            ExpandSpec("comparison_widen", ("type_gate",), expander="comparison_widen"),
            FuseSpec("route_merge", ("bridge_siblings", "comparison_widen"), params={"rrf_k": 60}, top_k=60),
            GateSpec(
                "confidence_gate",
                ("route_merge",),
                router="confidence_router",
                branches={"agree": ("fast_lane",), "disagree": ("rerank",)},
            ),
            TransformSpec("fast_lane", ("confidence_gate",), transformer="fast_lane"),
            RerankSpec("rerank", ("confidence_gate",), adapter="reranker", top_k=10),
            FuseSpec("final_selection", ("fast_lane", "rerank"), params={"rrf_k": 60}, top_k=10),
        ),
        ("final_selection",),
    )


def build_pipeline(corpus: DemoCorpus, settings: PipelineSettings) -> DAGPipeline:
    """Wire the operator graph to live adapters."""
    if settings.bm25_lane_enabled:
        bm25: Any = FixedDepthLane(
            BM25Adapter(corpus.index_text, retriever_id="bm25", tokenizer="whitespace"),
            settings.lane_depth,
            "bm25_lane",
            corpus.titles,
        )
    else:
        bm25 = DisabledLane("bm25_lane")

    vector_adapter: Any = (
        StaleIndexVectorLane(
            corpus.index_text,
            index_model=settings.dense_model,
            query_model=settings.stale_query_encoder,
            retriever_id="dense",
        )
        if settings.stale_query_encoder
        else HFBiEncoderAdapter(corpus.index_text, model_name=settings.dense_model, retriever_id="dense")
    )
    dense = FixedDepthLane(vector_adapter, settings.lane_depth, "dense_lane", corpus.titles)
    lanes = [bm25, dense]
    link_index = TitleMentionIndex(corpus.titles)

    base = _graph()
    graph = dataclasses.replace(
        base, operators=tuple(_apply_settings(spec, settings) for spec in base.operators)
    )
    return DAGPipeline(
        graph,
        {
            "bm25_lane": bm25,
            "dense_lane": dense,
            "type_router": _question_type_router,
            "confidence_router": _confidence_router,
            "bridge_hop2": _make_bridge_hop2(lanes, settings, corpus.titles),
            "bridge_siblings": _make_bridge_siblings(link_index, corpus, settings),
            "comparison_widen": _make_comparison_widen(lanes, settings),
            "fast_lane": _fast_lane,
            "reranker": CorpusReranker(settings.reranker_model, corpus.index_text),
        },
        service_id="retobs-flagship-demo",
    )


def _apply_settings(spec: Any, settings: PipelineSettings) -> Any:
    """Push the settings' k values into the graph's fuse/rerank specs."""
    top_k = {
        "hybrid_fusion": settings.fusion_top_k,
        "route_merge": settings.rerank_candidates,
        "rerank": settings.final_k,
        "final_selection": settings.final_k,
    }.get(spec.op_id)
    if top_k is None:
        return spec
    if spec.op_type == "FUSE":
        return dataclasses.replace(spec, params={"rrf_k": settings.rrf_k}, top_k=top_k)
    return dataclasses.replace(spec, top_k=top_k)


# --------------------------------------------------------------------------------------
# Run configuration (manifest + release identity)
# --------------------------------------------------------------------------------------


def _graph_config() -> GraphPipelineConfig:
    """Declare the DAG in retobs' config schema so it is recorded in the run manifest."""
    node = GraphNodeConfig
    return GraphPipelineConfig(
        id=PIPELINE_ID,
        nodes=[
            node(id="bm25_lane", type="adapter.bm25", op_type="SOURCE"),
            node(id="dense_lane", type="adapter.hf_biencoder", op_type="SOURCE"),
            node(id="hybrid_fusion", op="fuse", op_type="FUSE", inputs=["bm25_lane", "dense_lane"]),
            node(id="type_gate", type="adapter.import", op_type="GATE", inputs=["hybrid_fusion"]),
            node(id="bridge_hop2", type="adapter.import", op_type="EXPAND", inputs=["type_gate"]),
            node(id="bridge_siblings", type="adapter.import", op_type="EXPAND", inputs=["bridge_hop2"]),
            node(id="comparison_widen", type="adapter.import", op_type="EXPAND", inputs=["type_gate"]),
            node(id="route_merge", op="fuse", op_type="FUSE", inputs=["bridge_siblings", "comparison_widen"]),
            node(id="confidence_gate", type="adapter.import", op_type="GATE", inputs=["route_merge"]),
            node(id="fast_lane", type="adapter.import", op_type="TRANSFORM", inputs=["confidence_gate"]),
            node(id="rerank", type="adapter.hf_crossencoder", op_type="RERANK", inputs=["confidence_gate"]),
            node(id="final_selection", op="fuse", op_type="FUSE", inputs=["fast_lane", "rerank"]),
        ],
        output="final_selection",
    )


def index_build_id(corpus: DemoCorpus, settings: PipelineSettings) -> str:
    """Identity of the vector index actually searched.

    Derived from everything that changes the index's contents: the corpus, the embedding
    model, and how documents were turned into indexable text. Reusing this id while changing
    any of those is precisely the mistake the comparability scenario demonstrates.
    """
    payload = f"{corpus.fingerprint}|{settings.dense_model}|{CHUNKING_REVISION}"
    return f"faiss-flatip-{hashlib.sha256(payload.encode()).hexdigest()[:12]}"


def build_config(
    corpus: DemoCorpus,
    settings: PipelineSettings,
    *,
    experiment_name: str,
    dataset_name: str = "hotpotqa-demo",
    embedding_model_revision: str | None = None,
    index_build_id_override: str | None = None,
    seed: int = 20260803,
    concurrency: int = 8,
    timeout_seconds: int = 60,
) -> ExperimentConfig:
    """Build the run configuration, including the release identity retobs compares runs on."""
    return ExperimentConfig(
        experiment=ExperimentMeta(name=experiment_name),
        dataset=DatasetConfig(name=dataset_name),
        graphs=[_graph_config()],
        metrics=MetricsConfig(recall_at_k=[10], ndcg_at_k=[10], precision_at_k=[10], mrr=True),
        # retobs' 5s default timeout is sized for a single-shot retriever. This pipeline runs
        # up to four searches plus a cross-encoder pass per query, so it needs real headroom;
        # a timeout here would silently drop queries out of the metric means.
        execution=ExecutionConfig(
            concurrency=concurrency,
            seed=seed,
            cache_results=False,
            timeout_seconds=timeout_seconds,
        ),
        release_identity=ReleaseIdentityConfig(
            service_id="retobs-flagship-demo",
            deployment_revision=experiment_name,
            corpus_revision=corpus.fingerprint,
            index_build_id=index_build_id_override or index_build_id(corpus, settings),
            chunking_revision=CHUNKING_REVISION,
            embedding_model_revision=embedding_model_revision or settings.dense_model,
            reranker_model_revision=settings.reranker_model,
        ),
    )
