#!/usr/bin/env bash
# End-to-end dashboard demo: benchmark → train classifier → second run → serve UI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> Installing extras (demo, hf, dashboard, classifier)..."
pip install -e ".[demo,hf,dashboard,classifier]" -q

echo "==> Generating synthetic dataset..."
python examples/dashboard_demo/generate_data.py

echo "==> Building dashboard UI (production bundle)..."
make dashboard-build

echo "==> Run 1/2: benchmark all pipeline combinations..."
retobs run \
  --config examples/dashboard_demo/config.yaml \
  --latency-budget-ms 3000 \
  --no-cache

echo "==> Training query difficulty classifier from run diagnostics..."
retobs classifier train \
  --dataset observatory-demo \
  --db .retobs/dashboard_demo.db \
  --min-samples 30

echo "==> Run 2/2: re-benchmark with difficulty predictions attached..."
retobs run \
  --config examples/dashboard_demo/config.yaml \
  --latency-budget-ms 3000

echo ""
echo "==> Done. Start the dashboard:"
echo "    retobs serve --db .retobs/dashboard_demo.db"
echo ""
echo "Open http://localhost:8000"
echo "  • Select the latest run for full charts"
echo "  • Check two runs in the sidebar to open Run Comparison"
