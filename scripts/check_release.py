from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import tomllib


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"release check: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-assets", action="store_true")
    args = parser.parse_args()
    with (ROOT / "pyproject.toml").open("rb") as handle:
        version = str(tomllib.load(handle)["project"]["version"])
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if "## [Unreleased]" not in changelog:
        fail("CHANGELOG.md has no [Unreleased] section")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "check_markdown_links.py")], check=True)

    manifest_path = ROOT / "docs" / "assets" / "manifest.json"
    if args.require_assets and not manifest_path.exists():
        fail("docs/assets/manifest.json is missing; run scripts/generate_demo_assets.py")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("retobs_version") != version:
            fail(f"demo assets are for {manifest.get('retobs_version')}, package is {version}")
        for name, expected_hash in manifest.get("files", {}).items():
            path = manifest_path.parent / name
            if not path.exists():
                fail(f"generated asset is missing: {name}")
            import hashlib

            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected_hash:
                fail(f"generated asset changed without manifest regeneration: {name}")
    print(f"Release checks passed for retobs {version}.")


if __name__ == "__main__":
    main()
