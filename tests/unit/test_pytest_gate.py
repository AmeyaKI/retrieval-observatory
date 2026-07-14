import pytest

# Exceed the canonical n=20 paired-sample power floor so this fixture tests a
# decision-bearing regression rather than the deliberate low-power no-decision state.
N = 24
CORPUS = {f"d{i}": f"topic{i} content" for i in range(N)}
CORPUS["filler"] = "unrelated filler text"
QUERIES = [{"query_id": f"q{i}", "text": f"topic{i}", "relevant_doc_ids": [f"d{i}"]} for i in range(N)]


def _good(q):
    # gold doc (matches the query's topic) ranked first
    topic = q.strip()
    gold = "d" + topic.removeprefix("topic")
    return [gold, "filler"]


def _bad(q):
    # never returns the gold doc
    return ["filler"]


def test_retobs_fixture_passes_when_stable(retobs):
    baseline = retobs.run(_good, queries=QUERIES, corpus=CORPUS, k=5, name="p")
    candidate = retobs.run(_good, queries=QUERIES, corpus=CORPUS, k=5, name="p")
    retobs.assert_no_regression(candidate, baseline)  # identical pipelines -> no regression


def test_retobs_fixture_detects_regression(retobs):
    baseline = retobs.run(_good, queries=QUERIES, corpus=CORPUS, k=5, name="p")
    candidate = retobs.run(_bad, queries=QUERIES, corpus=CORPUS, k=5, name="p")
    with pytest.raises(AssertionError, match="regression"):
        retobs.assert_no_regression(candidate, baseline)
