from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SKIP_PARTS = {".git", ".venv", "node_modules", ".archive", "superpowers"}


def markdown_files() -> list[Path]:
    roots = [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "CODE_OF_CONDUCT.md"]
    roots.extend((ROOT / "docs").rglob("*.md"))
    return sorted(path for path in roots if path.is_file() and not SKIP_PARTS.intersection(path.parts))


def local_target(source: Path, raw: str) -> Path | None:
    target = raw.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:", "data:")):
        return None
    path_text = unquote(target.split("#", 1)[0])
    if not path_text:
        return None
    return (source.parent / path_text).resolve()


def main() -> int:
    failures: list[str] = []
    for source in markdown_files():
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for raw in LINK.findall(line):
                target = local_target(source, raw)
                if target is not None and not target.exists():
                    failures.append(f"{source.relative_to(ROOT)}:{line_number}: missing {raw}")
    if failures:
        print("Broken local Markdown links:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Markdown links passed: {len(markdown_files())} public files checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
