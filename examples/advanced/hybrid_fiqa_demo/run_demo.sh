#!/usr/bin/env bash
# Hybrid DAG demo across three BEIR datasets (subsampled by default: max_queries=50).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

echo "==> FiQA hybrid DAG (max_queries=50)"
retobs evaluate --config examples/advanced/hybrid_fiqa_demo/config_fiqa.yaml

echo "==> SciFact hybrid DAG"
retobs evaluate --config examples/advanced/hybrid_fiqa_demo/config_scifact.yaml

echo "==> NFCorpus hybrid DAG"
retobs evaluate --config examples/advanced/hybrid_fiqa_demo/config_nfcorpus.yaml

echo "Done. Open dashboard:"
echo "  retobs serve --db .retobs/hybrid_fiqa_demo.db"
echo "  # also: .retobs/hybrid_scifact_demo.db / .retobs/hybrid_nfcorpus_demo.db"
echo "  # In Investigate: the hybrid fan-in and rerank, with per-operator counts"
