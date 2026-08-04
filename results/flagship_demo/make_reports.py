#!/usr/bin/env python3
"""Render the decision report for every scenario, in all three formats.

Uses retobs' own report contract (`ro.compare(...)` -> `to_json` / `to_markdown` / `to_html`).
Nothing here formats a number itself.

Usage:
    python make_reports.py
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import retrieval_observatory as ro
from retrieval_observatory.store.sqlite import SQLiteStore

HERE = Path(__file__).parent
DEFAULT_DB = str(HERE / ".retobs" / "demo.db")

# slug -> (candidate run name, one-line description for the console)
SCENARIOS = {
    "scenario-a-improvement": ("candidate-wider-merge", "wider branch merge"),
    "scenario-b-regression": ("candidate-no-bm25", "keyword lane disabled"),
    "scenario-c-identity-contradiction": ("candidate-swapped-embedding", "same index id, different model"),
    "scenario-c2-stale-index": ("candidate-stale-index", "index never rebuilt after model swap"),
}


async def run_ids(db_path: str) -> dict[str, str]:
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    return {row["experiment_name"]: row["run_id"] for row in await store.list_runs()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--policy", default=str(HERE / "release-policy.yaml"))
    parser.add_argument("--out", type=Path, default=HERE / "reports")
    args = parser.parse_args()

    ids = asyncio.run(run_ids(args.db))
    if "baseline" not in ids:
        raise SystemExit(f"no run named 'baseline' in {args.db} — run run_demo.sh first")
    baseline = ids["baseline"]
    args.out.mkdir(parents=True, exist_ok=True)

    for slug, (candidate_name, description) in SCENARIOS.items():
        candidate = ids.get(candidate_name)
        if candidate is None:
            print(f"  skip {slug}: no run named '{candidate_name}'")
            continue
        report = ro.compare(baseline, candidate, db_path=args.db, policy=args.policy)
        for suffix, render in (("json", report.to_json), ("md", report.to_markdown), ("html", report.to_html)):
            (args.out / f"{slug}.{suffix}").write_text(render(), encoding="utf-8")
        verdict = (report.comparison or {}).get("release_decision", {}).get("status", "?")
        print(f"  {slug:<38}{verdict:<7}{description}")

    print(f"\n  baseline {baseline} -> {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
