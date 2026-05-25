from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

from retrieval_observatory.types import Query

# BEIR dataset names available through HuggingFace
BEIR_DATASETS = [
    "msmarco", "trec-covid", "nfcorpus", "nq", "hotpotqa", "fiqa",
    "arguana", "webis-touche2020", "cqadupstack", "quora", "dbpedia-entity",
    "scidocs", "fever", "climate-fever", "scifact", "signal1m", "trec-news", "robust04",
]


class BEIRDataset:
    """Loads a BEIR dataset via the HuggingFace `datasets` library."""

    def __init__(
        self,
        dataset_name: str,
        split: str = "test",
        max_queries: Optional[int] = None,
    ):
        # dataset_name can be "nfcorpus" or "beir/nfcorpus"
        self.dataset_name = dataset_name.removeprefix("beir/")
        self.split = split
        self.max_queries = max_queries
        self._corpus: Optional[Dict[str, str]] = None

    @property
    def corpus(self) -> Dict[str, str]:
        if self._corpus is None:
            raise RuntimeError("Call load() before accessing corpus")
        return self._corpus

    def load(self) -> Tuple[list, Dict[str, Set[str]]]:
        """Returns (queries, qrels) where qrels = {query_id: {doc_id, ...}}."""
        try:
            from beir import util
            from beir.datasets.data_loader import GenericDataLoader
        except ImportError as e:
            raise ImportError(
                "BEIR support requires the 'beir' package. "
                "Install with: pip install retrieval-observatory[beir]"
            ) from e

        import os
        import tempfile

        url = f"https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{self.dataset_name}.zip"
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "retrieval_observatory", "beir")
        data_path = os.path.join(cache_dir, self.dataset_name)

        if not os.path.exists(data_path):
            os.makedirs(cache_dir, exist_ok=True)
            zip_path = util.download_and_unzip(url, cache_dir)

        loader = GenericDataLoader(data_folder=data_path)
        corpus_raw, queries_raw, qrels_raw = loader.load(split=self.split)

        self._corpus = {doc_id: doc.get("text", "") for doc_id, doc in corpus_raw.items()}

        query_ids = list(queries_raw.keys())
        if self.max_queries is not None:
            query_ids = query_ids[: self.max_queries]

        queries = [
            Query(
                text=queries_raw[qid],
                k=100,
                query_id=qid,
            )
            for qid in query_ids
        ]

        qrels: Dict[str, Set[str]] = {
            qid: set(qrels_raw[qid].keys())
            for qid in query_ids
            if qid in qrels_raw
        }

        return queries, qrels
