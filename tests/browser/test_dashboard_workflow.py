"""Browser checks of the three dashboard workflows (Investigate, Connect, Audit) against a live server.

Seed and serve (model-free), then point the suite at the server:

    python tests/browser/seed_e2e.py DIR
    retobs serve --db DIR/demo/demo.db,DIR/project/.retobs/results.db --port 4100
    RETOBS_E2E_URL=http://127.0.0.1:4100 python -m pytest tests/browser -q

The demo database must be listed first: the landing redirect and legacy links carry no `db`, and
the dashboard falls back to the first registered database. Every run id, policy path and
integration id is read from `GET /demo/context`, `GET /dbs` and `GET /dbs/{db}/integrations`.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import pytest
from playwright.sync_api import Browser, Page, Playwright, Route, expect, sync_playwright

from retrieval_observatory.integrations.model import CAPABILITY_NAMES


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

# Records each response body the page finished reading, one macrotask after the read resolves, so a
# test can wait until a released (late) response has been handed to the UI before asserting on it.
SETTLE_SCRIPT = """(() => {
  window.__retobsSettled = [];
  for (const name of ['text', 'json']) {
    const original = Response.prototype[name];
    Response.prototype[name] = function () {
      const url = this.url;
      return original.call(this).then((value) => {
        setTimeout(() => window.__retobsSettled.push(url), 0);
        return value;
      });
    };
  }
})()"""
OUTCOME_TEXT = {
    "Relevant, delivered",
    "Relevant, excluded",
    "Retained below cutoff",
    "Not observed in retrieval",
    "Judged nonrelevant",
    "Unjudged",
    "Insufficient evidence",
}


# ── harness ──────────────────────────────────────────────────────────────────────────────────


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
    context.add_init_script(SETTLE_SCRIPT)
    page = context.new_page()
    yield page
    context.close()


def _get(path: str):
    with urlopen(f"{BASE_URL}{path}", timeout=10) as response:
        return json.loads(response.read())


@pytest.fixture(scope="session")
def demo() -> dict:
    context = _get("/demo/context")
    missing = [key for key in ("db_id", "baseline_run_id", "validation_run_id", "sample_query_id", "repaired_document", "policy_path") if not context.get(key)]
    assert not missing, f"/demo/context lacks {missing}; seed with tests/browser/seed_e2e.py"
    return context


def _investigate(demo: dict, run: str, **params: str) -> str:
    query = "&".join(f"{key}={quote(value, safe='')}" for key, value in {"db": demo["db_id"], "run": run, **params}.items())
    return f"{BASE_URL}/#/investigate?{query}"


def _audit(demo: dict, baseline: str, candidate: str) -> str:
    return (
        f"{BASE_URL}/#/audit?db={quote(demo['db_id'])}&baseline={quote(baseline)}&candidate={quote(candidate)}"
        f"&policy={quote(demo['policy_path'], safe='')}"
    )


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


def _no_horizontal_scroll(page: Page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def _wait_settled(page: Page, fragment: str, count: int = 1) -> None:
    """Wait until `count` responses whose URL contains `fragment` were read by the page, then two frames."""
    page.wait_for_function(
        "([fragment, count]) => window.__retobsSettled.filter((url) => url.includes(fragment)).length >= count",
        arg=[fragment, count],
    )
    page.evaluate("() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


def _hold(page: Page, matches: Callable[[str], bool]) -> list[Route]:
    """Hold every matching request (never fulfilled until the test continues it); others pass through."""
    held: list[Route] = []

    def handler(route: Route) -> None:
        if matches(route.request.url):
            held.append(route)
        else:
            route.continue_()

    page.route("**/*", handler)
    return held


def _wait_held(page: Page, held: list[Route], count: int) -> None:
    """Route handlers run while Playwright waits, so yield to it until `count` requests are held."""
    for _ in range(100):
        if len(held) >= count:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"expected {count} held request(s), got {len(held)}")


def _release(held: list[Route]) -> None:
    for route in held:
        try:
            route.continue_()
        except Exception:  # noqa: BLE001 - already handled when the page moved on
            pass


def _evidence_run(page: Page) -> str:
    """The `Run` of the Evidence details disclosure: it comes from the investigation response, not the URL."""
    return page.locator("details:has(> summary:text-is('Evidence details')) dt:text-is('Run') + dd").first.text_content().strip()


def _stage_card_text(page: Page, op_id: str) -> str:
    return page.evaluate(
        """(opId) => {
          const card = [...document.querySelectorAll('svg foreignObject button')].find((b) => (b.title || '').split('\\n')[1] === opId);
          return card ? card.textContent : null;
        }""",
        op_id,
    )


def _received(stages: list[dict], op_id: str) -> int:
    return sum(stage["candidates_received"] for stage in stages if stage["op_id"] == op_id)


def _journey_heading(page: Page):
    return page.locator("#journey-detail-title")


# ── 1. Investigate: landing, run graph, lost document ────────────────────────────────────────


@pytest.mark.parametrize("width", [390, 768, 1440])
def test_investigate_lost_document_is_responsive_and_accessible(page: Page, demo: dict, tmp_path: Path, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    baseline, query, document = demo["baseline_run_id"], demo["sample_query_id"], demo["repaired_document"]

    page.goto(f"{BASE_URL}/#/")
    expect(page).to_have_url(re.compile(r"#/investigate\?"))
    expect(page.get_by_role("heading", level=1)).to_have_text("Investigate")

    page.goto(_investigate(demo, baseline))
    expect(page.get_by_role("heading", level=1)).to_have_text(f"Run {baseline}")
    expect(page.locator('svg[role="group"][aria-label^="Pipeline "]')).to_be_visible()
    expect(page.locator('dl[aria-label="Legend"]')).to_contain_text("SKIPPED_BY_GATE")
    operator_table = page.get_by_text("Operator table (accessible equivalent)", exact=True)
    expect(operator_table).to_be_visible()
    operator_table.click()
    expect(page.locator("table:has(caption:text('Accessible operator table'))")).to_contain_text("recency_filter")
    assert _no_horizontal_scroll(page)
    assert _semantic_violations(page) == []
    # Axe results are asserted last so every other check of this workflow still runs.
    violations = {"run view": _wcag_aa_violations(page)}

    page.goto(_investigate(demo, baseline, view="documents", entity=document))
    row = page.locator("#investigate-view tbody tr[tabindex]", has_text=query)
    expect(row).to_contain_text("Relevant, excluded")
    expect(row).to_contain_text("✕")
    row.click()
    expect(page).to_have_url(re.compile(rf"query={re.escape(query)}"))
    detail = page.get_by_role("region", name=re.compile(rf"in query\s+{re.escape(query)}"))
    expect(detail).to_contain_text("✕ Relevant, excluded")
    expect(detail).to_contain_text(re.compile(r"loss boundary\s+recency_filter"))
    assert _no_horizontal_scroll(page)
    assert _semantic_violations(page) == []
    page.screenshot(path=tmp_path / f"investigate-{width}.png", full_page=True)
    violations["document view"] = _wcag_aa_violations(page)
    assert violations == {"run view": [], "document view": []}


# ── 2. Compare ───────────────────────────────────────────────────────────────────────────────


def test_compare_shows_the_recovered_document(page: Page, demo: dict) -> None:
    baseline, validation = demo["baseline_run_id"], demo["validation_run_id"]
    query, document = demo["sample_query_id"], demo["repaired_document"]
    page.goto(_investigate(demo, validation, view="queries", query=query, compare=baseline))

    expect(page.get_by_role("heading", name=re.compile(rf"Candidate {validation} against baseline {baseline}"))).to_be_visible()
    row = page.locator("table:has(caption:text('Paired journeys')) tbody tr", has_text=document)
    expect(row).to_contain_text("✓ Gained")
    expect(row).to_contain_text("excluded (recency_filter) → included")
    assert _semantic_violations(page) == []
    assert _wcag_aa_violations(page) == []


# ── 3. Audit ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("width", [390, 1440])
def test_audit_passes_and_links_changed_queries_into_investigate(page: Page, demo: dict, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    baseline, validation, query = demo["baseline_run_id"], demo["validation_run_id"], demo["sample_query_id"]
    page.goto(_audit(demo, baseline, validation))

    expect(page.get_by_role("heading", name=re.compile(r"^Decision:"))).to_contain_text("PASS")
    expect(page.get_by_role("region", name=re.compile(r"^Decision:"))).to_contain_text("exit code 0")
    compatibility = page.get_by_role("region", name=re.compile(r"^Compatibility:"))
    expect(compatibility.get_by_role("table", name="Provenance fields")).to_be_visible()
    changed = page.get_by_role("region", name="Changed queries").get_by_role("link", name=query)
    expect(changed).to_be_visible()
    assert _no_horizontal_scroll(page)
    assert _semantic_violations(page) == []
    violations = _wcag_aa_violations(page)

    changed.click()
    expect(page).to_have_url(re.compile(rf"#/investigate\?.*run={validation}.*query={query}.*compare={baseline}"))
    expect(page.get_by_role("heading", name=re.compile(rf"Candidate {validation} against baseline {baseline}"))).to_be_visible()
    assert violations == []


# ── 4. Connect ───────────────────────────────────────────────────────────────────────────────


def _databases_by_integrations() -> tuple[list[tuple[str, dict]], list[str]]:
    """(db id, integration summary) for every recorded integration, and the ids of databases with none."""
    found, empty = [], []
    for database in _get("/dbs"):
        items = _get(f"/dbs/{quote(database['db_id'])}/integrations")["integrations"]
        found.extend((database["db_id"], item) for item in items)
        if not items:
            empty.append(database["db_id"])
    return found, empty


def test_connect_renders_the_verified_integration(page: Page) -> None:
    found, _ = _databases_by_integrations()
    assert found, "no integration record is served; seed with tests/browser/seed_e2e.py"
    db, summary = found[0]
    record = _get(f"/dbs/{quote(db)}/integrations/{quote(summary['integration_id'], safe='')}")
    assert record["investigation"], "the seeded integration has no evaluation run"

    page.goto(f"{BASE_URL}/#/connect?db={quote(db)}&integration={quote(summary['integration_id'], safe='')}")
    panel = page.get_by_role("region", name=f"{record['service_id']} · {record['pipeline_id']}")
    capabilities = panel.get_by_role("table", name=f"Verified capabilities of {record['integration_id']}")
    rows = capabilities.locator("tbody tr")
    expect(rows).to_have_count(len(CAPABILITY_NAMES))
    for name in CAPABILITY_NAMES:
        label = name.replace("_", " ")
        expect(capabilities.locator("tr", has_text=label[0].upper() + label[1:])).to_contain_text("● ready")
    setup = panel.locator("pre", has_text="--phase plan")
    expect(setup).to_contain_text(f"retobs integrate {record['project_root']} --phase plan")
    expect(setup).to_contain_text("--phase apply")
    expect(setup).to_contain_text(f"--phase verify --db {record['db_path']}")
    assert _semantic_violations(page) == []
    violations = _wcag_aa_violations(page)

    run = record["investigation"]["run_id"]
    panel.get_by_role("link", name="Open the first investigation").click()
    expect(page).to_have_url(re.compile(rf"#/investigate\?db={re.escape(db)}&run={run}&pipeline={re.escape(record['pipeline_id'])}"))
    expect(page.get_by_role("heading", level=1)).to_have_text(f"Run {run}")
    expect(page.locator("#investigate-view tbody tr[tabindex]").first).to_be_visible()
    assert _evidence_run(page) == run
    assert violations == []


@pytest.mark.parametrize("width", [390, 1440])
def test_connect_without_integrations_shows_the_guided_steps(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    _, empty = _databases_by_integrations()
    assert empty, "every served database holds an integration; the demo database should hold none"
    page.goto(f"{BASE_URL}/#/connect?db={quote(empty[0])}")
    expect(page.get_by_role("heading", level=1)).to_have_text("Connect an existing retrieval pipeline")
    for step in ("Install", "Ask your coding agent", "Or do it by hand"):
        expect(page.get_by_role("heading", name=step, exact=True)).to_be_visible()
    expect(page.get_by_role("region", name="Verified integrations")).to_contain_text("No verified integration in this database yet")
    assert _no_horizontal_scroll(page)
    assert _semantic_violations(page) == []
    assert _wcag_aa_violations(page) == []


# ── 5. Keyboard only ─────────────────────────────────────────────────────────────────────────


def _tab_until(page: Page, predicate: str, arg: str | None = None, key: str = "Tab", limit: int = 150) -> None:
    for _ in range(limit):
        page.keyboard.press(key)
        if page.evaluate(f"(arg) => {{ const el = document.activeElement; return Boolean({predicate}); }}", arg):
            return
    raise AssertionError(f"{key} never reached an element where {predicate} ({arg})")


def _arrow_to_row(page: Page, text: str) -> None:
    for _ in range(50):
        if text in page.evaluate("document.activeElement.textContent"):
            return
        page.keyboard.press("ArrowDown")
    raise AssertionError(f"ArrowDown never reached a row containing {text}")


def _focus_ring(page: Page) -> tuple[str, float]:
    style, width = page.evaluate("(() => { const s = getComputedStyle(document.activeElement); return [s.outlineStyle, parseFloat(s.outlineWidth)] })()")
    return style, width


def test_keyboard_selects_query_document_and_operator(page: Page, demo: dict) -> None:
    baseline, query, document = demo["baseline_run_id"], demo["sample_query_id"], demo["repaired_document"]
    page.goto(_investigate(demo, baseline, view="queries"))
    expect(page.locator("#investigate-view tbody tr[tabindex]").first).to_be_visible()

    row = "el.matches('#investigate-view tbody tr[tabindex]')"
    _tab_until(page, row)
    _arrow_to_row(page, query)
    style, width = _focus_ring(page)
    assert style != "none" and width > 0, f"focused query row has no visible focus ring ({style} {width})"
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(rf"[?&]query={re.escape(query)}(&|$)"))

    expect(page.locator("#investigate-view tbody tr[tabindex]", has_text=document)).to_be_visible()
    _tab_until(page, row)
    _arrow_to_row(page, document)
    page.keyboard.press("Space")
    expect(page).to_have_url(re.compile(rf"[?&]entity={re.escape(quote(document, safe=''))}(&|$)"))
    expect(_journey_heading(page)).to_contain_text(f"{document} in query {query}")

    _tab_until(page, "el.closest('svg foreignObject') && (el.title || '').split('\\n')[1] === arg", "recency_filter", key="Shift+Tab")
    style, width = _focus_ring(page)
    assert style != "none" and width > 0, f"focused stage card has no visible focus ring ({style} {width})"
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"[?&]stage=recency_filter(&|$)"))
    expect(page).to_have_url(re.compile(rf"[?&]query={re.escape(query)}(&|$)"))


# ── 6. Stale responses never overwrite the newer scope ───────────────────────────────────────


def test_late_query_response_does_not_overwrite_the_newer_query(page: Page, demo: dict) -> None:
    baseline, query, document = demo["baseline_run_id"], demo["sample_query_id"], demo["repaired_document"]
    other = next(row["query_id"] for row in _get(f"/dbs/{demo['db_id']}/investigation/runs/{baseline}/queries")["rows"] if row["query_id"] != query)
    page.goto(_investigate(demo, baseline, view="queries", query=other, entity=document))
    expect(_journey_heading(page)).to_contain_text(f"in query {other}")

    stale = f"/queries/{quote(query)}"
    held = _hold(page, lambda url: stale in url)
    try:
        # Open query A (its response is held), then go back to query B, which completes.
        page.goto(_investigate(demo, baseline, view="queries", query=query, entity=document))
        _wait_held(page, held, 1)
        page.go_back()
        expect(page).to_have_url(re.compile(rf"query={other}"))
        expect(_journey_heading(page)).to_contain_text(f"in query {other}")
        _release(held)
        _wait_settled(page, stale)
    finally:
        _release(held)
    expect(_journey_heading(page)).to_contain_text(f"in query {other}")
    assert f"in query {query}" not in page.inner_text("main")


def test_late_run_response_does_not_overwrite_the_newer_run(page: Page, demo: dict) -> None:
    baseline, validation = demo["baseline_run_id"], demo["validation_run_id"]
    stages = {run: _get(f"/dbs/{demo['db_id']}/investigation/runs/{run}/queries?limit=1")["stages"] for run in (baseline, validation)}
    assert _received(stages[baseline], "select") != _received(stages[validation], "select"), "the two runs must differ at select"
    page.goto(_investigate(demo, validation))
    expect(page.locator("#investigate-view tbody tr[tabindex]").first).to_be_visible()

    stale = f"/investigation/runs/{baseline}/queries?"
    held = _hold(page, lambda url: stale in url)
    try:
        run = page.get_by_label("Run", exact=True)
        run.select_option(baseline)
        expect(page.get_by_role("status").filter(has_text="Loading queries")).to_be_visible()
        run.select_option(validation)
        expect(page.locator("#investigate-view tbody tr[tabindex]").first).to_be_visible()
        assert len(held) == 2, f"expected the list and aggregate requests of {baseline} to be held, got {len(held)}"
        _release(held)
        _wait_settled(page, stale, count=2)
    finally:
        _release(held)
    expect(page.get_by_role("heading", level=1)).to_have_text(f"Run {validation}")
    assert _evidence_run(page) == validation
    assert f"received {_received(stages[validation], 'select')} candidates" in _stage_card_text(page, "select")


def test_late_audit_response_does_not_overwrite_the_newer_pair(page: Page, demo: dict) -> None:
    baseline, validation = demo["baseline_run_id"], demo["validation_run_id"]
    first: list[Route] = []

    def hold_first(route: Route) -> None:
        if route.request.method == "POST" and route.request.url.endswith("/compare") and not first:
            first.append(route)
        else:
            route.continue_()

    page.route("**/compare", hold_first)
    try:
        # Roles reversed first (held), then the candidate changes: baseline → baseline run, candidate → validation run.
        page.goto(_audit(demo, validation, baseline))
        _wait_held(page, first, 1)
        page.get_by_label("Baseline", exact=True).select_option(baseline)
        expect(page.get_by_role("alert")).to_contain_text("same run")
        page.get_by_label("Candidate", exact=True).select_option(validation)
        expect(page.get_by_role("heading", name=re.compile(r"^Decision:"))).to_contain_text("PASS")
        assert len(first) == 1
        _release(first)
        _wait_settled(page, "/compare", count=2)
    finally:
        _release(first)
    expect(page.get_by_role("heading", name=re.compile(r"^Decision:"))).to_contain_text("PASS")
    expect(page.get_by_text("Loading the release audit…")).to_have_count(0)
    sources = page.get_by_role("region", name="Sources")
    assert sources.locator("dt:text-is('Run') + dd").first.text_content() == baseline


# ── 7. Failure states and retired links ──────────────────────────────────────────────────────


def test_investigation_list_failure_is_actionable_without_stale_rows(page: Page, demo: dict) -> None:
    baseline, validation = demo["baseline_run_id"], demo["validation_run_id"]
    page.goto(_investigate(demo, baseline))
    expect(page.locator("#investigate-view tbody tr[tabindex]").first).to_be_visible()

    failing = f"**/investigation/runs/{validation}/queries?*"
    page.route(failing, lambda route: route.fulfill(status=503, body='{"detail":"simulated outage"}', content_type="application/json"))
    page.get_by_label("Run", exact=True).select_option(validation)
    alert = page.get_by_role("alert").filter(has_text="The request failed")
    expect(alert).to_contain_text("simulated outage")
    expect(page.locator("#investigate-view tbody tr[tabindex]")).to_have_count(0)

    page.unroute(failing)
    alert.get_by_role("button", name="Retry").click()
    expect(page.locator("#investigate-view tbody tr[tabindex]").first).to_be_visible()
    assert _evidence_run(page) == validation


def test_legacy_query_link_redirects_into_investigate(page: Page, demo: dict) -> None:
    baseline, query = demo["baseline_run_id"], demo["sample_query_id"]
    page.goto(f"{BASE_URL}/#/runs/{baseline}/queries/{query}")
    expect(page).to_have_url(f"{BASE_URL}/#/investigate?run={baseline}&view=queries&query={query}")
    expect(page.get_by_role("heading", level=1)).to_have_text(f"Run {baseline}")
    expect(page.locator("#investigate-view")).to_contain_text(f"Query {query}")


def test_retired_destination_shows_the_migration_notice(page: Page) -> None:
    page.goto(f"{BASE_URL}/#/production")
    notice = page.get_by_role("note")
    expect(notice.get_by_role("heading", level=1)).to_have_text("#/production is no longer a destination")
    expect(notice.get_by_role("link", name="Open Investigate")).to_have_attribute("href", re.compile(r"^#/investigate"))


# ── 8. Colour is never the only carrier ──────────────────────────────────────────────────────


def test_outcomes_and_graph_states_carry_glyph_and_text(page: Page, demo: dict) -> None:
    baseline, query, document = demo["baseline_run_id"], demo["sample_query_id"], demo["repaired_document"]
    page.goto(_investigate(demo, baseline, view="documents", entity=document, query=query))
    expect(_journey_heading(page)).to_be_visible()

    cells = page.evaluate(
        """() => {
          const table = document.querySelector('#investigate-view table:has(tbody tr[tabindex])');
          const index = [...table.querySelectorAll('thead th')].findIndex((th) => th.textContent.includes('outcome'));
          return [...table.querySelectorAll('tbody tr')].map((tr) => {
            const cell = tr.children[index];
            const glyph = cell.querySelector('[aria-hidden="true"]');
            const clone = cell.cloneNode(true);
            clone.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
            return { glyph: glyph ? glyph.textContent.trim() : '', text: clone.textContent.replace(/#\\d+/, '').trim() };
          });
        }"""
    )
    assert cells, "no outcome cells rendered"
    for cell in cells:
        assert cell["glyph"] and cell["text"] in OUTCOME_TEXT, cell

    cards = page.evaluate(
        """() => [...document.querySelectorAll('svg foreignObject button')].map((button) => {
          const clone = button.cloneNode(true);
          clone.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
          return { id: (button.title || '').split('\\n')[1], text: clone.textContent.trim(), full: button.textContent };
        })"""
    )
    assert cards, "no stage cards rendered"
    for card in cards:
        assert card["text"], f"stage card {card['id']} carries no text"
    removal = next(card for card in cards if card["id"] == "recency_filter")
    assert "✕ removed" in removal["full"], removal

    page.goto(_investigate(demo, baseline, view="queries", query=query))
    expect(page.locator("#investigate-view tbody tr[tabindex]").first).to_be_visible()
    statuses = page.evaluate("() => [...document.querySelectorAll('svg foreignObject button')].map((b) => b.textContent)")
    for text in statuses:
        assert re.search(r"FIRED|SKIPPED_BY_GATE|ERROR|TIMEOUT|not observed for this query", text), text
