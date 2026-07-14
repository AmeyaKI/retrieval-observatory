from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

import tomllib
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"


def _version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(base_url: str) -> None:
    base_url = base_url.rstrip("/")
    context = json.loads(urlopen(f"{base_url}/demo/context", timeout=10).read())
    required = ("baseline_run_id", "candidate_run_id", "validation_run_id", "sample_query_id")
    missing = [key for key in required if not context.get(key)]
    if missing:
        raise RuntimeError(f"Demo context is missing: {', '.join(missing)}. Regenerate it with the current `retobs demo`.")

    ASSETS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        video_dir = ASSETS / ".video"
        browser_context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(video_dir),
            record_video_size={"width": 1440, "height": 900},
        )
        page = browser_context.new_page()
        routes = [
            ("comparison.png", "#/compare", "Run Comparison"),
            (
                "query-debugger.png",
                f"#/runs/{context['candidate_run_id']}/queries/{context['sample_query_id']}",
                "Query evidence",
            ),
            ("validated-fix.png", f"#/runs/{context['validation_run_id']}", "Run conclusion"),
        ]
        for filename, route, visible_text in routes:
            page.goto(f"{base_url}/{route}")
            page.get_by_text(visible_text, exact=False).first.wait_for()
            page.wait_for_timeout(700)
            page.screenshot(path=ASSETS / filename, full_page=True)
        video = page.video
        browser_context.close()
        video_path = Path(video.path())
        target_video = ASSETS / "retrieval-debugging-loop.webm"
        video_path.replace(target_video)
        browser.close()
        if video_dir.exists():
            video_dir.rmdir()

    files = ["comparison.png", "query-debugger.png", "validated-fix.png", "retrieval-debugging-loop.webm"]
    manifest = {
        "schema_version": 1,
        "retobs_version": _version(),
        "source": "scripts/generate_demo_assets.py",
        "demo_context": {key: context[key] for key in required},
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
