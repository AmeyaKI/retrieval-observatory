#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

pip install -e ".[demo,dashboard]" -q
python examples/advanced/temporal_demo/generate_data.py
retobs evaluate --config examples/advanced/temporal_demo/config.yaml

echo ""
echo "Done. Start dashboard:"
echo "  retobs serve --db .retobs/temporal_demo.db"
