"""
BEIR nfcorpus BM25 baseline demo.

Usage:
    pip install "retrieval-observatory[demo]"
    python examples/basic/beir_demo.py

This runs BM25 retrieval over the entire nfcorpus test split (323 queries,
3633 documents) and reports Recall@{1,5,10}, MRR, NDCG@10, and latency.
Results are saved to .retobs/beir_demo.db under the repository root.
It is equivalent to `retobs evaluate --config examples/basic/beir_demo.yaml`.
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    config_path = os.path.join(HERE, "beir_demo.yaml")
    result = subprocess.run(
        [sys.executable, "-m", "retrieval_observatory.cli", "evaluate", "--config", config_path],
        cwd=REPO_ROOT,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
