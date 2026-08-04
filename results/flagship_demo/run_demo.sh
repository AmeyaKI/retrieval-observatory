#!/usr/bin/env bash
# Build the dataset (if absent), run every scenario, and write the reports.
#
#   ./run_demo.sh              400 queries per run  (~4 min, ~1.3 GB)
#   ./run_demo.sh 100          quick pass
#
# No API keys. No network beyond the first HotpotQA download and the two model pulls.
set -euo pipefail

cd "$(dirname "$0")"
PY="${PY:-python}"
N="${1:-400}"
DB=".retobs/demo.db"
POLICY="release-policy.yaml"
REPORTS="reports"

# `run.py` prints `run_id: <id>` on completion. Capturing it is deliberate: resolving ids by
# position afterwards is how you end up comparing a candidate against itself, or backwards.
launch() {
  local name="$1"; shift
  echo "  -> $name" >&2   # progress goes to stderr; stdout is the run id and nothing else
  "$PY" run.py --name "$name" --max-queries "$N" "$@" | awk '/^run_id:/{print $2}'
}

# The baseline's index id, read back from its manifest. Passed as argv rather than
# interpolated into a heredoc, which silently swallowed the surrounding quotes.
index_build_id() {
  "$PY" -c '
import asyncio, sys
from retrieval_observatory.store.sqlite import SQLiteStore
async def main():
    store = SQLiteStore(db_path=sys.argv[1])
    await store.init_db()
    print((await store.get_run_manifest(sys.argv[2]))["release_identity"]["index_build_id"])
asyncio.run(main())' "$DB" "$1"
}

echo "== dataset =="
if [ -f data/corpus.jsonl ]; then
  echo "  cached (delete data/ to rebuild)"
else
  "$PY" build_corpus.py
fi

echo "== runs ($N queries each) =="
rm -rf "$DB"; mkdir -p "$REPORTS"
BASELINE=$(launch baseline)
WIDER=$(launch candidate-wider-merge --merge-width 100)
NOBM25=$(launch candidate-no-bm25 --no-bm25)
SWAPPED=$(launch candidate-swapped-embedding \
  --embedding-model sentence-transformers/all-MiniLM-L12-v2 \
  --claim-index-build-id "$(index_build_id "$BASELINE")")
STALE=$(launch candidate-stale-index --stale-query-encoder sentence-transformers/all-MiniLM-L12-v2)

echo "== reports =="
"$PY" make_reports.py --db "$DB" --policy "$POLICY" --out "$REPORTS"

echo "== scenario D: candidate lineage =="
QUERY=$("$PY" inspect_run.py --run-id "$BASELINE" --pick | tail -1)
"$PY" inspect_run.py --run-id "$BASELINE" --trace "$QUERY" > "$REPORTS/scenario-d-lineage.txt"
"$PY" inspect_run.py --run-id "$BASELINE" > "$REPORTS/baseline-summary.txt"
echo "  -> $REPORTS/scenario-d-lineage.txt   (query $QUERY)"

cat <<SUMMARY

== done ==
  baseline                       $BASELINE
  candidate-wider-merge          $WIDER
  candidate-no-bm25              $NOBM25
  candidate-swapped-embedding    $SWAPPED
  candidate-stale-index          $STALE

  reports/    JSON, Markdown and HTML per scenario
  dashboard:  retobs serve --db $DB
              then open  #/runs/$BASELINE/queries/$QUERY
SUMMARY
