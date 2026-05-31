from retrieval_observatory.classifier.features import FEATURE_NAMES, extract_features


def test_extract_features_basic():
    feats = extract_features("What is hybrid retrieval?")
    assert feats["token_count"] == 4
    assert feats["question_type_what"] == 1.0
    assert feats["question_type_other"] == 0.0
    assert len(feats) == len(FEATURE_NAMES)


def test_extract_features_empty():
    feats = extract_features("")
    assert feats["token_count"] == 0
    assert feats["lexical_density"] == 0.0


def test_temporal_anchor():
    feats = extract_features("News since 2020 about climate")
    assert feats["has_temporal_anchor"] == 1.0


def test_negation_and_comparison():
    feats = extract_features("Which is better than the other, not worse?")
    assert feats["has_negation"] == 1.0
    assert feats["has_comparison"] == 1.0


def test_multi_clause():
    feats = extract_features("First part, second part, and third")
    assert feats["multi_clause"] == 1.0


def test_named_entity_density():
    feats = extract_features("Who founded OpenAI in California?")
    assert feats["named_entity_density"] > 0
