from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$")
SKIP_PARTS = {".git", ".venv", "node_modules", ".archive", "superpowers", "verification", "retobs_audit_remediation"}


def markdown_files() -> list[Path]:
    roots = [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "SECURITY.md",
        ROOT / "CODE_OF_CONDUCT.md",
    ]
    roots.extend((ROOT / "docs").rglob("*.md"))
    roots.extend((ROOT / "examples").rglob("*.md"))
    return sorted(path for path in roots if path.is_file() and not SKIP_PARTS.intersection(path.parts))


def local_target(source: Path, raw: str) -> tuple[Path | None, str | None]:
    target = raw.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("http://", "https://", "mailto:", "data:")):
        return None, None
    path_text, separator, anchor = unquote(target).partition("#")
    if not path_text:
        return source, anchor if separator else None
    return (source.parent / path_text).resolve(), anchor if separator else None


def heading_id(text: str) -> str:
    normalized = re.sub(r"[`*_]", "", text).lower()
    normalized = re.sub(r"[^\w\s-]", "", normalized)
    return re.sub(r"[\s-]+", "-", normalized).strip("-")


def heading_ids(path: Path) -> set[str]:
    return {
        heading_id(match.group(1))
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := HEADING.match(line))
    }


def main() -> int:
    failures: list[str] = []
    anchors: dict[Path, set[str]] = {}
    for source in markdown_files():
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for raw in LINK.findall(line):
                target, anchor = local_target(source, raw)
                if target is None:
                    continue
                if not target.exists():
                    failures.append(f"{source.relative_to(ROOT)}:{line_number}: missing {raw}")
                elif anchor:
                    ids = anchors.setdefault(target, heading_ids(target))
                    if anchor not in ids:
                        failures.append(f"{source.relative_to(ROOT)}:{line_number}: missing anchor {raw}")
    if failures:
        print("Broken local Markdown links:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Markdown links passed: {len(markdown_files())} public files checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
