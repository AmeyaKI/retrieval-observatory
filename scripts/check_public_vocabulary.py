from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "contracts/forbidden_vocabulary.json").read_text(encoding="utf-8"))
TEXT_SUFFIXES = {".html", ".json", ".md", ".py", ".toml", ".tsx", ".ts", ".yaml", ".yml"}


def excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    return any(
        relative == item or relative.startswith(f"{item}/") or item in path.relative_to(ROOT).parts
        for item in CONFIG["exclude"]
    )


def main() -> int:
    failures: list[str] = []
    patterns = [(re.compile(raw), replacement) for raw, replacement in CONFIG["patterns"].items()]
    for root_name in CONFIG["scan_roots"]:
        root = ROOT / root_name
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or excluded(path) or path.suffix not in TEXT_SUFFIXES:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for pattern, replacement in patterns:
                    if pattern.search(line):
                        failures.append(f"{path.relative_to(ROOT)}:{line_number}: {pattern.pattern!r}; {replacement}")
    if failures:
        print("Forbidden active vocabulary:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Active public vocabulary contains no removed terms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
