"""Capture the README screenshots and a short recording from `retobs demo` served locally.

    retobs demo
    retobs serve --db .retobs/demo/results.db      # from the repository root
    python scripts/generate_demo_assets.py         # writes docs/assets/ and its manifest

Every page is one of the three workflows on the two demo runs: the baseline's lost document in
Investigate, the validation run compared against the baseline, and the release audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import tomllib
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
VIDEO = "retrieval-debugging-loop.webm"
STILL_HEIGHT = 1500
# Local paths must never reach a published image.
PRIVATE_MARKERS = ("/Users/", "/home/", "/private/", "/tmp/")


def _version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_relative(path: str) -> str:
    resolved = Path(path).resolve()
    return os.path.relpath(resolved, ROOT) if resolved.is_relative_to(ROOT) else path


def _pages(context: dict) -> list[tuple[str, str, str]]:
    """(file name, hash route, text that proves the page rendered its evidence)."""
    db, pipeline = quote(context["db_id"]), "golden-hybrid"
    baseline, validation = quote(context["baseline_run_id"]), quote(context["validation_run_id"])
    query, entity = quote(context["sample_query_id"]), quote(context["repaired_document"], safe="")
    policy = quote(_repo_relative(context["policy_path"]), safe="")
    return [
        (
            "investigate-lost-document.png",
            f"#/investigate?db={db}&run={baseline}&pipeline={pipeline}&view=documents&query={query}&entity={entity}",
            "Relevant, excluded",
        ),
        (
            "investigate-compare.png",
            f"#/investigate?db={db}&run={validation}&pipeline={pipeline}&view=queries&query={query}&compare={baseline}",
            "Paired journeys",
        ),
        (
            "audit-pass.png",
            f"#/audit?db={db}&baseline={baseline}&candidate={validation}&policy={policy}",
            "exit code 0",
        ),
    ]


def _open(page, url: str, visible_text: str) -> None:
    page.goto(url)
    page.get_by_text(visible_text, exact=False).first.wait_for()
    page.wait_for_timeout(700)
    text = page.inner_text("body")
    leaked = [marker for marker in PRIVATE_MARKERS if marker in text]
    if leaked:
        raise RuntimeError(f"{url} renders a local path ({', '.join(leaked)}); refusing to publish it.")


def generate(base_url: str) -> None:
    base_url = base_url.rstrip("/")
    context = json.loads(urlopen(f"{base_url}/demo/context", timeout=10).read())
    required = ("db_id", "baseline_run_id", "validation_run_id", "sample_query_id", "repaired_document", "policy_path")
    missing = [key for key in required if not context.get(key)]
    if missing:
        raise RuntimeError(f"Demo context is missing: {', '.join(missing)}. Regenerate it with the current `retobs demo`.")

    pages = _pages(context)
    ASSETS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        # The dashboard scrolls inside its own panel, so a full-page capture is the viewport:
        # stills use a tall viewport, the recording a normal one.
        stills = browser.new_page(viewport={"width": 1440, "height": STILL_HEIGHT})
        for filename, route, visible_text in pages:
            _open(stills, f"{base_url}/{route}", visible_text)
            stills.screenshot(path=ASSETS / filename)
        video_dir = ASSETS / ".video"
        recording = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(video_dir),
            record_video_size={"width": 1440, "height": 900},
        )
        page = recording.new_page()
        for _, route, visible_text in pages:
            _open(page, f"{base_url}/{route}", visible_text)
            page.get_by_text(visible_text, exact=False).first.scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
        video = page.video
        recording.close()
        Path(video.path()).replace(ASSETS / VIDEO)
        browser.close()
        if video_dir.exists():
            video_dir.rmdir()

    files = [filename for filename, _, _ in pages] + [VIDEO]
    manifest = {
        "schema_version": 2,
        "retobs_version": _version(),
        "source": "scripts/generate_demo_assets.py",
        "demo": "retobs demo (golden hybrid fixture)",
        "pages": {filename: route for filename, route, _ in pages},
        "files": {name: _sha256(ASSETS / name) for name in files},
    }
    (ASSETS / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture versioned retobs demo screenshots and a short workflow recording.")
    parser.add_argument("--base-url", default="http://127.0.0.1:4000")
    args = parser.parse_args()
    generate(args.base_url)


if __name__ == "__main__":
    main()
