"""
BEIR nfcorpus BM25 baseline demo.

Usage:
    pip install retobs[demo]
    python examples/beir_demo.py

This runs BM25 retrieval over the entire nfcorpus test split (323 queries,
3633 documents) and reports Recall@{1,5,10}, MRR, NDCG@10, and latency.
Results are saved to .retobs/beir_demo.db.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import os

# Ensure we can import from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    config_path = os.path.join(os.path.dirname(__file__), "beir_demo.yaml")
    result = subprocess.run(
        [sys.executable, "-m", "retrieval_observatory.cli", "run", "--config", config_path, "--skip-smoke-test"],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
