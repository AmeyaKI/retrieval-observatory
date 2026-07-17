from pathlib import Path
import yaml

from retrieval_observatory.integrations.model import IntegrationManifest


def write_manifest(root: Path, manifest: IntegrationManifest) -> Path:
    path = root / "retobs" / "integration.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest.to_dict(), sort_keys=False), encoding="utf-8")
    return path


def load_manifest(root: Path) -> IntegrationManifest:
    return IntegrationManifest.from_dict(yaml.safe_load((root / "retobs" / "integration.yaml").read_text(encoding="utf-8")))
