from retrieval_observatory.forge.scenarios.entity_ambiguity import EntityAmbiguityDetector


def test_entity_ambiguity_detector_finds_shared_token():
    corpus = {
        "d1": {"title": "Meta", "text": "Meta, formerly known as Facebook, rebranded in 2021."},
        "d2": {"title": "Meta Quest", "text": "Meta, also known as the metaverse company, released Quest 3."},
    }
    found = EntityAmbiguityDetector(max_scenarios=5).detect(corpus)
    assert len(found) >= 1
    assert found[0].scenario_type == "entity_ambiguity"


def test_entity_ambiguity_scenario_id_stable_across_runs():
    # Item 0: scenario_id must be content-derived (not a random uuid) so regenerating the
    # same corpus reproduces the same scenario id.
    corpus = {
        "d1": {"title": "Meta", "text": "Meta, formerly known as Facebook, rebranded in 2021."},
        "d2": {"title": "Meta Quest", "text": "Meta, also known as the metaverse company, released Quest 3."},
    }
    a = EntityAmbiguityDetector(max_scenarios=5).detect(corpus)
    b = EntityAmbiguityDetector(max_scenarios=5).detect(corpus)
    assert [s.scenario_id for s in a] == [s.scenario_id for s in b]
