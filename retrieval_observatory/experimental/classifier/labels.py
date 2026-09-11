from __future__ import annotations

BUCKET_TO_CLASS = {
    "easy": "easy",
    "medium": "medium",
    "hard": "hard",
    "discriminative": "hard",
    "unstable": "medium",
}

CLASS_NAMES = ("easy", "medium", "hard")


def to_training_class(bucket: str) -> str | None:
    """Map post-hoc difficulty bucket to a 3-class training label."""
    if bucket == "unknown":
        return None
    return BUCKET_TO_CLASS.get(bucket)


def normalize_dataset_name(name: str) -> str:
    """Normalize dataset identifiers for matching (e.g. beir/nfcorpus vs nfcorpus)."""
    name = (name or "").strip().lower()
    if name.startswith("beir/"):
        return name
    if name in {
        "nfcorpus", "trec-covid", "nq", "hotpotqa", "fiqa", "arguana", "quora",
        "dbpedia-entity", "scidocs", "fever", "climate-fever", "scifact", "trec-news",
    }:
        return f"beir/{name}"
    return name


def dataset_slug(dataset_name: str) -> str:
    """Filesystem-safe slug for model artifacts."""
    return normalize_dataset_name(dataset_name).replace("/", "_")


def default_model_path(dataset_name: str, base_dir: str = ".retobs/models") -> str:
    return f"{base_dir}/query_difficulty_{dataset_slug(dataset_name)}.joblib"
