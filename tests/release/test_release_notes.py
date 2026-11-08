"""GitHub Release notes come from the version's CHANGELOG summary, never from nothing."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("release_notes", Path(__file__).resolve().parents[2] / "scripts" / "release_notes.py")
release_notes = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## [Unreleased]

### Added

## [1.2.0] — 2026-01-02

The summary of 1.2.0.
Second line.

### Added
- something

## [1.1.0] — 2026-01-01

### Fixed
- no summary here
"""


def test_notes_carry_the_summary_and_links() -> None:
    text = release_notes.notes(CHANGELOG, "1.2.0")

    assert text.startswith("The summary of 1.2.0.\nSecond line.\n\n")
    assert "/blob/v1.2.0/CHANGELOG.md" in text
    assert "pypi.org/project/retrieval-observatory/1.2.0/" in text
    assert "something" not in text


def test_a_pre_release_uses_its_final_version_section() -> None:
    assert release_notes.summary(CHANGELOG, "1.2.0rc2") == "The summary of 1.2.0.\nSecond line."


@pytest.mark.parametrize("version", ["9.9.9", "1.1.0"])
def test_missing_section_or_summary_is_an_error(version: str) -> None:
    with pytest.raises(SystemExit):
        release_notes.summary(CHANGELOG, version)


def test_every_published_release_has_a_summary() -> None:
    changelog = (Path(__file__).resolve().parents[2] / "CHANGELOG.md").read_text(encoding="utf-8")
    for version in ("0.6.0", "0.7.0", "0.8.0"):
        assert release_notes.summary(changelog, version)
