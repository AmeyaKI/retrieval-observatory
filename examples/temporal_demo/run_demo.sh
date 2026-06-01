#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

pip install -e ".[demo,dashboard]" -q
python examples/temporal_demo/generate_data.py
retobs run --config examples/temporal_demo/config.yaml --no-cache

echo ""
echo "Done. Start dashboard:"
echo "  retobs serve --db .retobs/temporal_demo.db"
