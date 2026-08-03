#!/usr/bin/env python3
"""Build the flagship demo's corpus, queries, and ground truth from raw HotpotQA.

Everything here is a mechanical transformation of HotpotQA's own human annotations.
No LLM is involved, nothing is synthesized, and no relevance judgment is invented:

  corpus  — every distinct paragraph bundled with a sampled question, deduplicated by title.
  queries — the sampled questions, carrying HotpotQA's `type` and `level` labels as metadata.
  qrels   — each question's `supporting_facts` titles, at binary relevance.

Rerun with the same --seed and --n-queries to regenerate byte-identical outputs.

Usage:
    python build_corpus.py                       # writes ./data/
    python build_corpus.py --out-dir /tmp/hotpot --n-queries 400
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

DATASET = "hotpotqa/hotpot_qa"
CONFIG = "distractor"
SPLIT = "validation"

DEFAULT_SEED = 20260803
DEFAULT_N_QUERIES = 1300

# A declared slice with fewer paired queries than this cannot support a meaningful
# bootstrap confidence interval, so the build fails loudly rather than producing a
# dataset that would silently turn every release decision into a sample-size BLOCK.
MIN_SLICE_QUERIES = 50


def doc_id_for(title: str) -> str:
    """Stable, filesystem- and URL-safe document id derived from the paragraph title.

    Title-derived rather than positional, so the same Wikipedia paragraph keeps the same
    id no matter which questions happen to be sampled. The hash suffix disambiguates
    titles that collapse to the same slug (e.g. punctuation-only differences).
    """
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:80] or "untitled"
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return f"{slug}__{digest}"


def paragraph_text(sentences: list[str]) -> str:
    return " ".join(s.strip() for s in sentences if s.strip())


def build(seed: int, n_queries: int, out_dir: Path) -> dict:
    try:
        from datasets import load_dataset
    except ImportError:
        sys.exit("This script needs the `datasets` package: pip install datasets")

    print(f"Loading {DATASET} [{CONFIG}] split={SPLIT} ...")
    split = load_dataset(DATASET, CONFIG, split=SPLIT)
    print(f"  {len(split)} questions available")

    if n_queries > len(split):
        sys.exit(f"--n-queries {n_queries} exceeds the {len(split)} available questions")

    rng = random.Random(seed)
    sampled_indices = sorted(rng.sample(range(len(split)), n_queries))

    corpus: dict[str, dict] = {}
    title_conflicts: list[str] = []
    queries: list[dict] = []
    qrels: list[dict] = []
    missing_support: list[str] = []

    for index in sampled_indices:
        row = split[index]
        question_id = str(row["id"])

        # Corpus: every paragraph bundled with this question (2 supporting + 8 distractors).
        # Deduplicated across questions by title — the same Wikipedia article reached from
        # two different questions is one document, not two.
        for title, sentences in zip(row["context"]["title"], row["context"]["sentences"]):
            document_id = doc_id_for(title)
            text = paragraph_text(sentences)
            existing = corpus.get(document_id)
            if existing is None:
                corpus[document_id] = {"id": document_id, "title": title, "text": text}
            elif existing["text"] != text:
                # Same title, different body across two questions. Keep the first-seen text
                # (sampling order is deterministic) and record it so the count is auditable.
                title_conflicts.append(title)

        # Ground truth: the titles HotpotQA's annotators named as supporting facts.
        supporting_titles = sorted(set(row["supporting_facts"]["title"]))
        relevant_ids = [doc_id_for(title) for title in supporting_titles]
        if not relevant_ids:
            missing_support.append(question_id)
            continue
        for document_id in relevant_ids:
            qrels.append({"query_id": question_id, "doc_id": document_id, "grade": 1})

        queries.append({
            "query_id": question_id,
            "text": row["question"],
            "metadata": {"type": row["type"], "level": row["level"]},
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "corpus.jsonl", (corpus[key] for key in sorted(corpus)))
    _write_jsonl(out_dir / "queries.jsonl", queries)
    _write_jsonl(out_dir / "qrels.jsonl", qrels)

    manifest = {
        "source": {
            "dataset": DATASET,
            "config": CONFIG,
            "split": SPLIT,
            "split_size": len(split),
            "license": "CC BY-SA 4.0",
            "citation": (
                "Yang, Z., Qi, P., Zhang, S., Bengio, Y., Cohen, W. W., Salakhutdinov, R., "
                "& Manning, C. D. (2018). HotpotQA: A Dataset for Diverse, Explainable "
                "Multi-hop Question Answering. EMNLP 2018."
            ),
        },
        "sampling": {"seed": seed, "n_requested": n_queries, "n_kept": len(queries)},
        "counts": {
            "queries": len(queries),
            "corpus_documents": len(corpus),
            "qrel_pairs": len(qrels),
            "relevant_per_query_mean": round(len(qrels) / len(queries), 3) if queries else 0,
        },
        "distribution": {
            "type": dict(Counter(q["metadata"]["type"] for q in queries)),
            "level": dict(Counter(q["metadata"]["level"] for q in queries)),
            "type_x_level": {
                f"{t}|{lv}": n
                for (t, lv), n in sorted(
                    Counter((q["metadata"]["type"], q["metadata"]["level"]) for q in queries).items()
                )
            },
        },
        "integrity": {
            "questions_dropped_no_supporting_facts": len(missing_support),
            "title_text_conflicts": len(title_conflicts),
        },
        "fingerprints": {
            name: _sha256(out_dir / name)
            for name in ("corpus.jsonl", "queries.jsonl", "qrels.jsonl")
        },
    }
    (out_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def report(manifest: dict) -> int:
    counts = manifest["counts"]
    print("\n" + "=" * 62)
    print("HotpotQA flagship demo dataset")
    print("=" * 62)
    print(f"  queries             {counts['queries']:>7,}")
    print(f"  corpus documents    {counts['corpus_documents']:>7,}")
    print(f"  qrel pairs          {counts['qrel_pairs']:>7,}"
          f"   ({counts['relevant_per_query_mean']} relevant per query)")
    print(f"  seed                {manifest['sampling']['seed']:>7}")

    thin: list[str] = []
    for field in ("type", "level"):
        print(f"\n  by {field}:")
        for value, n in sorted(manifest["distribution"][field].items(), key=lambda kv: -kv[1]):
            flag = "" if n >= MIN_SLICE_QUERIES else f"   << under {MIN_SLICE_QUERIES}"
            print(f"    {value:<14} {n:>7,}{flag}")
            if n < MIN_SLICE_QUERIES:
                thin.append(f"{field}={value} ({n})")

    integrity = manifest["integrity"]
    if integrity["questions_dropped_no_supporting_facts"]:
        print(f"\n  dropped (no supporting facts): "
              f"{integrity['questions_dropped_no_supporting_facts']}")
    if integrity["title_text_conflicts"]:
        print(f"  title/text conflicts resolved first-seen: {integrity['title_text_conflicts']}")

    if thin:
        print(f"\n  WARNING: too thin for a meaningful confidence interval: {', '.join(thin)}")
        print("  Do not declare these as required release-policy slices.")
        return 1
    print(f"\n  All slice groups clear the {MIN_SLICE_QUERIES}-query floor.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-queries", type=int, default=DEFAULT_N_QUERIES)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "data")
    args = parser.parse_args()

    manifest = build(args.seed, args.n_queries, args.out_dir)
    status = report(manifest)
    print(f"\n  written to {args.out_dir}/")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
