from retrieval_observatory.store.base import normalize_dataset_name


def test_normalize_dataset_name():
    assert normalize_dataset_name("nfcorpus") == "beir/nfcorpus"
    assert normalize_dataset_name(" BEIR/nfcorpus ") == "beir/nfcorpus"
    assert normalize_dataset_name("custom") == "custom"
