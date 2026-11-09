#!/usr/bin/env python3
"""Print the GitHub Release notes for a version, from its CHANGELOG.md section.

    python scripts/release_notes.py 0.8.1            # notes for the 0.8.1 release
    python scripts/release_notes.py 0.7.0rc3         # a pre-release uses its final version's section

The notes are the section's summary (the text between the version heading and its first ``###``
heading), followed by links to the full changelog at the tag and to the PyPI page. A version with
no section, or a section with no summary, is an error: a release is never published without notes.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/AmeyaKI/retrieval-observatory"


def final_version(version: str) -> str:
    """``0.7.0rc3`` -> ``0.7.0``; a final version is returned unchanged."""
    return re.sub(r"(a|b|rc)\d+$", "", version)


def summary(changelog: str, version: str) -> str:
    release = final_version(version)
    heading = re.search(rf"^## \[{re.escape(release)}\][^\n]*\n", changelog, flags=re.MULTILINE)
    if heading is None:
        raise SystemExit(f"CHANGELOG.md has no section for {release}")
    rest = changelog[heading.end():]
    end = re.search(r"^(###|## )", rest, flags=re.MULTILINE)
    text = (rest[: end.start()] if end else rest).strip()
    if not text:
        raise SystemExit(f"CHANGELOG.md section {release} has no summary paragraph")
    return text


def notes(changelog: str, version: str) -> str:
    return (
        f"{summary(changelog, version)}\n\n"
        f"Full changelog: {REPOSITORY}/blob/v{version}/CHANGELOG.md\n"
        f"PyPI: https://pypi.org/project/retrieval-observatory/{version}/\n"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    args = parser.parse_args(argv)
    sys.stdout.write(notes((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), args.version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
