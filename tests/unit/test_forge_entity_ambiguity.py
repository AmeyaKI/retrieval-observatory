from retrieval_observatory.forge.scenarios.entity_ambiguity import EntityAmbiguityDetector


def test_entity_ambiguity_detector_finds_shared_token():
    corpus = {
        "d1": {"title": "Apple pricing", "text": "Apple released new pricing in 2024."},
        "d2": {"title": "Apple orchards", "text": "Apple harvest season begins in fall."},
    }
    found = EntityAmbiguityDetector(max_scenarios=5).detect(corpus)
    assert len(found) >= 1
    assert found[0].scenario_type == "entity_ambiguity"
