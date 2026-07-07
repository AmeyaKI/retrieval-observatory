#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

pip install -e ".[demo]" -q
python examples/advanced/custom_retriever/generate_data.py

export PYTHONPATH="${ROOT}/examples/advanced/custom_retriever:${PYTHONPATH:-}"

retobs run --config examples/advanced/custom_retriever/config.yaml --no-cache

echo ""
echo "Done. Inspect results:"
echo "  retobs serve --db .retobs/custom_retriever.db"
