# Data provenance

## Source


| Item          | Answer                                                                     |
| ------------- | -------------------------------------------------------------------------- |
| Dataset       | `[hotpotqa/hotpot_qa](https://huggingface.co/datasets/hotpotqa/hotpot_qa)` |
| Configuration | `distractor`                                                               |
| Split used    | `validation` (7,405 questions)                                             |
| License       | **CC BY-SA 4.0**                                                           |
| Homepage      | [https://hotpotqa.github.io/](https://hotpotqa.github.io/)                 |


**Citation**

> Yang, Z., Qi, P., Zhang, S., Bengio, Y., Cohen, W. W., Salakhutdinov, R., & Manning, C. D. (2018).
> *HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question Answering.*
> Proceedings of the 2018 Conference on Empirical Methods in Natural Language Processing (EMNLP).

HotpotQA is distributed under CC BY-SA 4.0. Derived data in `data/` — the corpus, queries, and
relevance judgments — is a transformation of that source and carries the same license.

## This is real human-annotated ground truth, not synthetic data

Every relevance judgment used to score this demo comes from HotpotQA's `supporting_facts` field:
the paragraphs that human annotators identified as necessary to answer each question. No language
model was used to generate questions, to judge relevance, or to expand the labels. Nothing was
hand-mapped. `build_corpus.py` is a mechanical transformation of fields that already exist in the
published dataset.

## How each artifact is derived

`queries.jsonl` — 1,300 questions sampled from the validation split with
`random.Random(20260803).sample(...)`, using each question's original HotpotQA `id`. HotpotQA's own
`type` and `level` labels are carried through as query metadata; those are what the release policy's
declared slices filter on. The train split is never used.

`corpus.jsonl` — HotpotQA bundles 10 paragraphs with each question (the 2 supporting ones plus
8 automatically-selected distractors). Every paragraph across all 1,300 sampled questions is pooled
and deduplicated by title, yielding 12,654 distinct documents. Document text is the paragraph's
sentences joined with single spaces. Document ids are derived from the title
(`slugified_title__sha1prefix`), so the same Wikipedia paragraph keeps the same id regardless of
which questions were sampled.

`qrels.jsonl` — for each question, the titles named in `supporting_facts` are mapped to their
document ids at binary relevance (grade 1). This yields exactly 2 relevant documents per question,
matching HotpotQA's two-hop design.

## Known characteristics and limitations

**The validation split contains only** `level: hard` **questions.** All 7,405 of them. This is by
design in HotpotQA — easy and medium questions appear only in the train split, which is excluded
from evaluation here. The `level` slice is therefore declared and reported, but its numbers are
identical to the overall aggregate by construction. `type` (bridge / comparison) is the axis that
actually varies.

**Relevance labels are positive-only.** HotpotQA records which paragraphs support an answer; it
never records which paragraphs are irrelevant. Consequently, when retobs classifies the outcome of
each retrieved candidate, roughly 2 documents per question can be judged relevant and the remaining
~12,652 are genuinely unlabeled. Candidates that were retrieved and dropped are therefore classified
`unknown_relevance` rather than `irrelevant_removed`. **This is retobs correctly refusing to guess,
not a tracing failure.** The signal to watch for tracing health is `lineage_incomplete`, which means
retobs could not reconstruct what happened to a candidate at all.

**One title/text conflict, resolved deterministically.** The paragraph titled
`Good Night (The Simpsons short)` appears with two byte-different bodies across the sampled
questions. The texts are identical apart from non-breaking spaces (`\xa0`) where the other copy uses
ordinary spaces. The first-seen copy wins; sampling order is deterministic, so this resolves the
same way on every rerun. Counted in `dataset_manifest.json` under
`integrity.title_text_conflicts`.

**No questions were dropped.** All 1,300 sampled questions had usable supporting-facts
annotations (`integrity.questions_dropped_no_supporting_facts: 0`).

## Reproducing

```bash
python build_corpus.py                    # defaults: seed 20260803, 1300 queries
python build_corpus.py --n-queries 200    # smaller set for a quick check
```

`dataset_manifest.json` records the seed, the counts, the distributions, and a SHA-256 fingerprint
of each output file. Rerunning with the same arguments reproduces all three fingerprints exactly
(verified).

`data/` is regenerable and is not committed to the repository.