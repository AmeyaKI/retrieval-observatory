from retrieval_observatory.classifier.labels import (
    BUCKET_TO_CLASS,
    default_model_path,
    normalize_dataset_name,
    to_training_class,
)


def test_to_training_class_mapping():
    assert to_training_class("easy") == "easy"
    assert to_training_class("medium") == "medium"
    assert to_training_class("hard") == "hard"
    assert to_training_class("discriminative") == "hard"
    assert to_training_class("unstable") == "medium"
    assert to_training_class("unknown") is None


def test_normalize_dataset_name():
    assert normalize_dataset_name("nfcorpus") == "beir/nfcorpus"
    assert normalize_dataset_name("beir/nfcorpus") == "beir/nfcorpus"
    assert normalize_dataset_name("custom") == "custom"


def test_default_model_path():
    assert "query_difficulty_beir_nfcorpus" in default_model_path("beir/nfcorpus")


def test_all_buckets_mapped():
    for bucket in ("easy", "medium", "hard", "discriminative", "unstable"):
        assert bucket in BUCKET_TO_CLASS
