#!/usr/bin/env bash
# Run BEIR publish benchmark configs.
# Usage: ./scripts/run_beir_publish.sh smoke|full-sweep|cohere-nfcorpus|cascade-nfcorpus|smoke-cascade
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Reduce OpenMP/threading issues on macOS during FAISS/dense encoding
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export KMP_DUPLICATE_LIB_OK=TRUE
export TOKENIZERS_PARALLELISM=false

if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

RETOBS=(python -m retrieval_observatory.cli)

run_config() {
  local config="$1"
  echo "==> retobs validate --config $config"
  "${RETOBS[@]}" validate --config "$config"
  echo "==> retobs run --config $config --no-cache"
  "${RETOBS[@]}" run --config "$config" --no-cache
}

load_cohere_env() {
  if [[ -f .env ]]; then
    set -a
    # shellcheck source=/dev/null
    source .env
    set +a
  fi
  if [[ -z "${COHERE_API_KEY:-}" ]]; then
    echo "Warning: COHERE_API_KEY not set; Cohere configs will fail." >&2
  fi
}

TARGET="${1:-smoke}"

case "$TARGET" in
  smoke)
    run_config examples/beir_publish/smoke_nfcorpus.yaml
    run_config examples/beir_publish/smoke_scifact.yaml
    run_config examples/beir_publish/smoke_fiqa.yaml
    load_cohere_env
    run_config examples/beir_publish/smoke_cohere_nfcorpus.yaml
    run_config examples/beir_publish/smoke_cascade_nfcorpus.yaml
    ;;
  smoke-sweep)
    run_config examples/beir_publish/smoke_nfcorpus.yaml
    run_config examples/beir_publish/smoke_scifact.yaml
    run_config examples/beir_publish/smoke_fiqa.yaml
    ;;
  smoke-cohere)
    load_cohere_env
    run_config examples/beir_publish/smoke_cohere_nfcorpus.yaml
    ;;
  smoke-cascade)
    run_config examples/beir_publish/smoke_cascade_nfcorpus.yaml
    ;;
  full-sweep)
    run_config examples/beir_publish/sweep_nfcorpus.yaml
    run_config examples/beir_publish/sweep_scifact.yaml
    run_config examples/beir_publish/sweep_fiqa.yaml
    ;;
  cohere-nfcorpus)
    load_cohere_env
    run_config examples/beir_publish/cohere_nfcorpus.yaml
    ;;
  cascade-nfcorpus)
    run_config examples/beir_publish/cascade_nfcorpus.yaml
    ;;
  *)
    echo "Unknown target: $TARGET" >&2
    echo "Usage: $0 smoke|smoke-sweep|smoke-cohere|smoke-cascade|full-sweep|cohere-nfcorpus|cascade-nfcorpus" >&2
    exit 1
    ;;
esac

echo "Done: $TARGET"
