from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect, sync_playwright


BASE_URL = os.environ.get("RETOBS_E2E_URL")
AXE_SOURCE = (
    Path(__file__).parents[2]
    / "retrieval_observatory"
    / "dashboard"
    / "ui"
    / "node_modules"
    / "axe-core"
    / "axe.min.js"
)
pytestmark = [pytest.mark.browser, pytest.mark.skipif(not BASE_URL, reason="RETOBS_E2E_URL is not set")]


@pytest.fixture(scope="session")
def browser_engine() -> Iterator[tuple[Playwright, Browser]]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield playwright, browser
        browser.close()


@pytest.fixture
def page(browser_engine: tuple[Playwright, Browser]) -> Iterator[Page]:
    _, browser = browser_engine
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


def _semantic_violations(page: Page) -> list[str]:
    return page.evaluate(
        """() => {
          const issues = [];
          const ids = [...document.querySelectorAll('[id]')].map((node) => node.id);
          for (const id of new Set(ids)) if (ids.filter((item) => item === id).length > 1) issues.push(`duplicate id: ${id}`);
          for (const node of document.querySelectorAll('button, a[href], input, select')) {
            const labels = 'labels' in node ? [...node.labels].map((label) => label.textContent).join(' ') : '';
            const name = (node.getAttribute('aria-label') || node.getAttribute('title') || labels || node.textContent || '').trim();
            if (!name) issues.push(`unnamed interactive element: ${node.outerHTML.slice(0, 80)}`);
          }
          for (const image of document.querySelectorAll('img')) if (!image.hasAttribute('alt')) issues.push(`image missing alt: ${image.src}`);
          return issues;
        }"""
    )


def _wcag_aa_violations(page: Page) -> list[str]:
    if not AXE_SOURCE.is_file():
        pytest.fail("axe-core is not installed; run npm ci in retrieval_observatory/dashboard/ui")
    page.add_script_tag(path=str(AXE_SOURCE))
    result = page.evaluate(
        """async () => await axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
          resultTypes: ['violations']
        })"""
    )
    return [
        (
            f"{violation['id']}: {violation['help']} — "
            + "; ".join(
                f"{', '.join(node['target'])}: {node['failureSummary']}"
                for node in violation["nodes"]
            )
        )
        for violation in result["violations"]
    ]


@pytest.mark.parametrize("width", [390, 768, 1440])
def test_golden_workflow_is_responsive_and_semantic(page: Page, tmp_path: Path, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    context = page.request.get(f"{BASE_URL}/demo/context").json()
    baseline = context["baseline_run_id"]
    query_id = context["sample_query_id"]

    page.goto(f"{BASE_URL}/#/runs/{baseline}")
    expect(page.get_by_role("heading", name="Run conclusion")).to_be_visible()
    expect(page.get_by_text("Evidence:", exact=False).first).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert _semantic_violations(page) == []
    assert _wcag_aa_violations(page) == []
    page.screenshot(path=tmp_path / f"run-{width}.png", full_page=True)

    page.goto(f"{BASE_URL}/#/runs/{baseline}/queries/{query_id}")
    expect(page.get_by_role("heading", name="Query evidence")).to_be_visible()
    expect(page.get_by_text("Relevant document movement", exact=True)).to_be_visible()
    assert _semantic_violations(page) == []
    assert _wcag_aa_violations(page) == []

    page.goto(f"{BASE_URL}/#/compare")
    expect(page.get_by_text("Baseline", exact=False).first).to_be_visible()
    expect(page.get_by_text("Candidate", exact=False).first).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert _wcag_aa_violations(page) == []

    page.goto(f"{BASE_URL}/#/benchmarks/run/{baseline}/queries/{query_id}")
    expect(page).to_have_url(f"{BASE_URL}/#/runs/{baseline}/queries/{query_id}")

    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement !== document.body")


def test_run_api_failure_renders_actionable_error_state(page: Page) -> None:
    context = page.request.get(f"{BASE_URL}/demo/context").json()
    baseline = context["baseline_run_id"]
    page.route("**/metrics*", lambda route: route.fulfill(status=503, body='{"detail":"simulated"}', content_type="application/json"))
    page.goto(f"{BASE_URL}/#/runs/{baseline}")
    expect(page.get_by_text("Failed to fetch metrics", exact=False)).to_be_visible()
