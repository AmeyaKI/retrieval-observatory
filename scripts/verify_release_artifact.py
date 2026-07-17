from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    value.update(path.read_bytes())
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.manifest.read_text(encoding="utf-8"))
    actual = {path.name: digest(path) for path in sorted(args.dist.iterdir()) if path.suffix in {".whl", ".gz"}}
    if actual != expected["sha256"]:
        raise SystemExit(f"release artifact digest mismatch: expected={expected['sha256']} actual={actual}")
    print("Release artifacts match tested SHA-256 manifest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
