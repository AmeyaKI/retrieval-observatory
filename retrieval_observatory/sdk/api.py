from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Union

from retrieval_observatory.sdk.report import BenchmarkReport, ReportModel, _run_sync
from retrieval_observatory.sdk.wrappers import as_retriever

if TYPE_CHECKING:
    from retrieval_observatory.release.policy import ReleasePolicy

# Code-first entry point. Mirrors `retobs run` but takes live Python objects instead of YAML,
# routing through the same shared executor so artifacts + query lineage are identical.

PipelineInput = Union[Any, Sequence[Any]]

_BEIR_PREFIX = "beir/"


class _FusedStage:
    """Marker for a fan-in (parallel-retriever) candidate-generation stage.

    Produced by :func:`fuse`. Wraps several retrievers that run concurrently and are
    combined (default: Reciprocal Rank Fusion) into a single stage-0 snapshot whose
    documents are the *union* of all arms. This is what makes hybrid pipelines accurate:
    diagnostics like ``candidate_miss`` see every arm's candidates, not just one.
    """

    def __init__(
        self,
        retrievers: Sequence[Any],
        *,
        method: str = "rrf",
        rrf_k: int = 60,
        fetch_k: int = 100,
        top_k: int = 100,
        retriever_id: str = "fused",
    ):
        arms = list(retrievers)
        if len(arms) < 2:
            raise ValueError("fuse() needs at least two retrievers to combine.")
        if method != "rrf":
            raise ValueError(f"Unknown fusion method '{method}'. Only 'rrf' is supported.")
        self.retrievers = arms
        self.method = method
        self.rrf_k = rrf_k
        self.fetch_k = fetch_k
        self.top_k = top_k
        self.retriever_id = retriever_id


def fuse(
    retrievers: Sequence[Any],
    *,
    method: str = "rrf",
    rrf_k: int = 60,
    fetch_k: int = 100,
    top_k: int = 100,
    retriever_id: str = "fused",
) -> _FusedStage:
    """Combine several retrievers into one parallel (fan-in) candidate-generation stage.

    Use as stage 0 of a hybrid pipeline::

        ro.benchmark([ro.fuse([bm25, dense]), rerank], queries=Q, corpus=C)

    A nested list/tuple in the pipeline is accepted as a convenience alias for the same
    thing (``ro.benchmark([[bm25, dense], rerank])``) — the outer list is the sequence of
    stages, an inner list is the set of parallel arms for that stage.
    """
    return _FusedStage(
        retrievers,
        method=method,
        rrf_k=rrf_k,
        fetch_k=fetch_k,
        top_k=top_k,
        retriever_id=retriever_id,
    )


def retriever(fn: Optional[Callable] = None, *, retriever_id: Optional[str] = None):
    """Decorator marking a callable as a retriever (optionally naming it)."""
    def wrap(f: Callable) -> Callable:
        if retriever_id:
            f._retobs_retriever_id = retriever_id  # type: ignore[attr-defined]
        return f

    return wrap(fn) if fn is not None else wrap


def reranker(fn: Optional[Callable] = None, *, retriever_id: Optional[str] = None):
    """Decorator marking a callable as a reranker (optionally naming it)."""
    def wrap(f: Callable) -> Callable:
        f._retobs_role = "reranker"  # type: ignore[attr-defined]
        if retriever_id:
            f._retobs_retriever_id = retriever_id  # type: ignore[attr-defined]
        return f

    return wrap(fn) if fn is not None else wrap


def benchmark(
    pipeline: PipelineInput,
    dataset: Optional[Any] = None,
    *,
    queries: Optional[Sequence[Any]] = None,
    corpus: Optional[Any] = None,
    qrels: Optional[Dict[str, Any]] = None,
    k: int = 10,
    metrics: Optional[Dict[str, Any]] = None,
    labels: str = "gold",
    judge: Optional[str] = None,
    judge_model: Optional[str] = None,
    name: Optional[str] = None,
    db_path: str = ".retobs/results.db",
    concurrency: int = 8,
    max_queries: Optional[int] = None,
    cache: bool = False,
) -> BenchmarkReport:
    """Benchmark a retrieval pipeline defined in Python.

    `pipeline`: a callable, an object with `.retrieve`/`.rerank`, a LangChain/LlamaIndex
    retriever, or a list of these (stage 0 retriever, later stages rerankers).
    `dataset`: a "beir/<name>" string, a dataset object with `.load()`, or None to use
    `queries`/`corpus`/`qrels`.
    `labels`: "gold" (use provided qrels), "llm-judge" (grade retrieved docs with an LLM —
    no ground truth needed), or "pooled" (merge gold + judged). `judge` selects the provider
    ("gemini"/"openai"/"anthropic") and `judge_model` the model id.
    """
    return _run_sync(
        _benchmark_async(
            pipeline=pipeline,
            dataset=dataset,
            queries=queries,
            corpus=corpus,
            qrels=qrels,
            k=k,
            metrics=metrics,
            labels=labels,
            judge=judge,
            judge_model=judge_model,
            name=name,
            db_path=db_path,
            concurrency=concurrency,
            max_queries=max_queries,
            cache=cache,
        )
    )


def evaluate(
    pipeline: PipelineInput,
    dataset: Optional[Any] = None,
    **kwargs: Any,
) -> BenchmarkReport:
    """Evaluate a Python retrieval callable/object and return the canonical run report.

    This is the task-oriented name for :func:`benchmark`; both execute the same
    runtime and persist the same manifest, traces, metrics, diagnostics, and lineage.
    """
    return benchmark(pipeline, dataset=dataset, **kwargs)


def compare(
    baseline: BenchmarkReport | str,
    candidate: BenchmarkReport | str,
    *,
    db_path: Optional[str] = None,
    policy: str | Path | ReleasePolicy | None = None,
) -> ReportModel:
    """Compare explicit baseline/candidate Runs and return the canonical report model."""
    from retrieval_observatory.sdk.report import load_comparison_report

    baseline_id = baseline.run_id if isinstance(baseline, BenchmarkReport) else str(baseline)
    candidate_id = candidate.run_id if isinstance(candidate, BenchmarkReport) else str(candidate)
    resolved_db = db_path
    if resolved_db is None and isinstance(candidate, BenchmarkReport):
        resolved_db = candidate.db_path
    if resolved_db is None and isinstance(baseline, BenchmarkReport):
        resolved_db = baseline.db_path
    return _run_sync(
        load_comparison_report(
            baseline_id,
            candidate_id,
            resolved_db or ".retobs/results.db",
            policy=policy,
        )
    )


def inspect_query(
    run_id: str,
    query_id: str,
    *,
    db_path: str = ".retobs/results.db",
    trace_limit: int = 20,
    trace_offset: int = 0,
) -> Dict[str, Any]:
    """Return the canonical database- and Run-scoped QueryEvidence document."""
    from pathlib import Path

    from retrieval_observatory.evidence import build_query_evidence
    from retrieval_observatory.store.sqlite import SQLiteStore

    async def _load() -> Dict[str, Any]:
        store = SQLiteStore(db_path=db_path)
        await store.init_db()
        return await build_query_evidence(
            store,
            db_id=Path(db_path).stem,
            run_id=run_id,
            query_id=query_id,
            trace_limit=min(max(trace_limit, 1), 100),
            trace_offset=max(trace_offset, 0),
        )

    return _run_sync(_load())


async def _benchmark_async(
    *,
    pipeline,
    dataset,
    queries,
    corpus,
    qrels,
    k,
    metrics,
    labels,
    judge,
    judge_model,
    name,
    db_path,
    concurrency,
    max_queries,
    cache,
) -> BenchmarkReport:
    from retrieval_observatory.config.schema import (
        DatasetConfig,
        ExecutionConfig,
        ExperimentConfig,
        ExperimentMeta,
        LabelsConfig,
        MetricsConfig,
        PipelineConfig,
        StageConfig,
    )
    from retrieval_observatory.pipeline.factory import build_pipeline
    from retrieval_observatory.runner.execute import execute_benchmark
    from retrieval_observatory.store.sqlite import SQLiteStore

    ds_obj, dataset_name = _resolve_dataset(dataset, queries, corpus, qrels, k, max_queries)
    loaded_queries, loaded_qrels = ds_obj.load()
    if max_queries is not None:
        loaded_queries = loaded_queries[:max_queries]
        ids = {q.query_id for q in loaded_queries}
        loaded_qrels = {qid: rel for qid, rel in loaded_qrels.items() if qid in ids}
    corpus_map = ds_obj.corpus if hasattr(ds_obj, "corpus") else None

    stages, stage_ids = _build_stages(pipeline, corpus_map)
    pipeline_id = name or "__".join(stage_ids)
    pipeline_obj = build_pipeline(
        pipeline_id=pipeline_id,
        stages=stages,
        k_per_stage=[k] * len(stages),
    )

    metrics_cfg = MetricsConfig(**metrics) if metrics else MetricsConfig()
    cfg = ExperimentConfig(
        experiment=ExperimentMeta(name=name or "sdk-benchmark"),
        dataset=DatasetConfig(name=dataset_name),
        pipelines=[
            PipelineConfig(
                id=pipeline_id,
                stages=[StageConfig(type="adapter.import", retriever_id=sid) for sid in stage_ids],
            )
        ],
        labels=LabelsConfig(mode=_labels_mode(labels), judge=judge, model=judge_model),
        metrics=metrics_cfg,
        execution=ExecutionConfig(concurrency=concurrency, cache_results=cache),
    )

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    artifacts = await execute_benchmark(
        cfg=cfg,
        dataset=ds_obj,
        queries=loaded_queries,
        qrels=loaded_qrels,
        corpus=corpus_map,
        pipelines=[pipeline_obj],
        store=store,
        no_cache=not cache,
    )
    return BenchmarkReport(artifacts, db_path=db_path, experiment_name=cfg.experiment.name)


def generate_testset(
    corpus: Any,
    *,
    n_per_type: int = 3,
    query_types: Sequence[str] = ("comparison", "constraint", "long_tail"),
    scenario_types: Sequence[str] = ("temporal", "alias"),
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    k: int = 10,
    validate: bool = True,
):
    """Synthesize a benchmark test set (queries + ground truth) from your corpus via Test Sets.

    Returns an in-memory dataset object usable directly as `benchmark(..., dataset=<here>)`.
    The default `query_types` are rule-based and need no API key; pass `provider=` (and an
    api key / env var) to enable LLM query types like paraphrase/temporal/adversarial.

    When ``validate=True`` (default), Test Sets expands extractive qrels with an LLM judge when
    a provider or ``GOOGLE_API_KEY`` / ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` is available.
    """
    return _run_sync(
        _generate_testset_async(
            corpus=corpus,
            n_per_type=n_per_type,
            query_types=list(query_types),
            scenario_types=list(scenario_types),
            provider=provider,
            api_key=api_key,
            model=model,
            k=k,
            validate=validate,
        )
    )


def _forge_judge(provider: Optional[str], api_key: Optional[str], model: Optional[str]):
    """Return an LLMJudge when credentials are available, else None."""
    from retrieval_observatory.datasets.llm_judge import AnthropicJudge, GeminiJudge, OpenAIJudge

    def _ready(judge) -> bool:
        return bool(getattr(judge, "_api_key", None))

    chosen = (provider or "").lower()

    def _try_gemini():
        return GeminiJudge(api_key=api_key, model=model or "gemini-2.0-flash")

    def _try_openai():
        return OpenAIJudge(api_key=api_key, model=model or "gpt-4o-mini")

    def _try_anthropic():
        return AnthropicJudge(api_key=api_key, model=model or "claude-haiku-4-5-20251001")

    if chosen in ("gemini", "google"):
        try:
            judge = _try_gemini()
            return judge if _ready(judge) else None
        except (ValueError, ImportError):
            return None
    if chosen == "openai":
        judge = _try_openai()
        return judge if _ready(judge) else None
    if chosen in ("anthropic", "claude"):
        judge = _try_anthropic()
        return judge if _ready(judge) else None
    if chosen:
        raise ValueError(f"Unknown LLM provider '{provider}'. Use gemini, openai, or anthropic.")

    for factory in (_try_gemini, _try_openai, _try_anthropic):
        try:
            judge = factory()
            if _ready(judge):
                return judge
        except (ValueError, ImportError):
            continue
    return None


async def _generate_testset_async(
    *,
    corpus,
    n_per_type,
    query_types,
    scenario_types,
    provider,
    api_key,
    model,
    k,
    validate,
):
    import warnings

    from retrieval_observatory.datasets.inmemory import InMemoryDataset
    from retrieval_observatory.forge.engine import ForgeEngine
    from retrieval_observatory.forge.stress.suite import StressTestSuite

    forge_corpus = _to_forge_corpus(corpus)
    generator = None
    if provider:
        from retrieval_observatory.forge.generation.generator import ForgeGenerator

        generator = ForgeGenerator.from_provider(provider, api_key=api_key, model=model)

    judge = None
    if validate:
        judge = _forge_judge(provider, api_key, model)
        if judge is None:
            warnings.warn(
                "generate_testset(validate=True) but no LLM judge is available; "
                "pass provider= or set GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY. "
                "Using extractive qrels only.",
                UserWarning,
                stacklevel=2,
            )
            validate = False

    engine = ForgeEngine(forge_corpus, generator=generator, scenario_types=list(scenario_types))
    dataset = await engine.run(
        query_types=list(query_types),
        n_per_type=n_per_type,
        validate=validate,
        judge=judge,
    )
    bench_queries, qrels = StressTestSuite(dataset).to_benchmark_inputs()
    flat_corpus = {doc_id: doc.get("text", "") for doc_id, doc in forge_corpus.items()}
    return InMemoryDataset(queries=bench_queries, corpus=flat_corpus, qrels=qrels, k=k)


def _to_forge_corpus(corpus: Any) -> Dict[str, Dict]:
    """Normalize a corpus into Test Sets's {doc_id: {"text": ...}} shape."""
    if isinstance(corpus, dict):
        out: Dict[str, Dict] = {}
        for doc_id, value in corpus.items():
            if isinstance(value, dict):
                out[str(doc_id)] = value
            else:
                out[str(doc_id)] = {"text": str(value)}
        return out
    # Sequence of {"id":, "text":, ...}
    return {str(obj["id"]): {"text": obj.get("text", ""), **{kk: vv for kk, vv in obj.items() if kk not in ("id", "text")}} for obj in corpus}


def _labels_mode(labels: str) -> str:
    mapping = {"gold": "gold", "llm-judge": "llm_judge", "llm_judge": "llm_judge", "pooled": "pooled_llm_judge"}
    if labels not in mapping:
        raise ValueError(f"Unknown labels mode '{labels}'. Use one of {sorted(mapping)}.")
    return mapping[labels]


def _resolve_dataset(dataset, queries, corpus, qrels, k, max_queries):
    """Return (dataset_object, dataset_name)."""
    if isinstance(dataset, str):
        if dataset.startswith(_BEIR_PREFIX):
            from retrieval_observatory.datasets.beir import BEIRDataset

            return BEIRDataset(dataset_name=dataset, split="test", max_queries=max_queries), dataset
        raise ValueError(
            f"String dataset '{dataset}' not recognized. Use a 'beir/<name>' id, "
            "or pass queries=/corpus=/qrels= for a custom dataset."
        )
    if dataset is not None and hasattr(dataset, "load"):
        name = getattr(dataset, "name", None) or getattr(getattr(dataset, "dataset_name", None), "__str__", lambda: "custom")()
        return dataset, str(name)
    if queries is None:
        raise ValueError("Provide either `dataset=` or `queries=` (with optional corpus=/qrels=).")
    from retrieval_observatory.datasets.inmemory import InMemoryDataset

    return InMemoryDataset(queries=queries, corpus=corpus, qrels=qrels, k=k), "custom"


def _build_fused_stage(spec: "_FusedStage", corpus_map: Optional[Dict[str, str]]):
    """Build an RRFFusionAdapter (stage 0) from a fan-in spec."""
    from retrieval_observatory.adapters.rrf_adapter import RRFFusionAdapter

    arms = [
        as_retriever(
            arm,
            corpus=corpus_map,
            retriever_id=getattr(arm, "_retobs_retriever_id", None),
            role="retriever",
        )
        for arm in spec.retrievers
    ]
    return RRFFusionAdapter(
        retrievers=arms,
        retriever_id=spec.retriever_id,
        rrf_k=spec.rrf_k,
        fetch_k=spec.fetch_k,
        top_k=spec.top_k,
    )


def _build_stages(pipeline: PipelineInput, corpus_map: Optional[Dict[str, str]]):
    items = list(pipeline) if isinstance(pipeline, (list, tuple)) else [pipeline]
    stages = []
    stage_ids: List[str] = []
    for i, item in enumerate(items):
        # Fan-in stage: an explicit ro.fuse(...) marker, or a nested list/tuple of arms.
        is_nested = isinstance(item, (list, tuple))
        if isinstance(item, _FusedStage) or is_nested:
            if i != 0:
                raise ValueError(
                    "A fused / parallel stage (ro.fuse([...]) or a nested list) is only valid "
                    "as stage 0 (candidate generation), not as a reranker stage."
                )
            spec = item if isinstance(item, _FusedStage) else _FusedStage(list(item))
            stage = _build_fused_stage(spec, corpus_map)
            stage_id = stage.retriever_id
            stages.append(stage)
            stage_ids.append(stage_id)
            continue
        role = "retriever" if i == 0 else "reranker"
        if getattr(item, "_retobs_role", None) == "reranker":
            role = "reranker"
        rid = getattr(item, "_retobs_retriever_id", None)
        stage = as_retriever(item, corpus=corpus_map, retriever_id=rid, role=role)
        stage_id = getattr(stage, "retriever_id", None) or f"stage{i}"
        # Disambiguate duplicate ids so pipeline_id and stage attribution stay readable.
        if stage_id in stage_ids:
            stage_id = f"{stage_id}_{i}"
            stage.retriever_id = stage_id
        stages.append(stage)
        stage_ids.append(stage_id)
    return stages, stage_ids
