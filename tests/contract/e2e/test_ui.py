"""End-to-end tests of the Contractors screen (Playwright).
Run with: pytest tests/e2e -m e2e --browser chromium   (APP_BASE_URL required)

The screen reads data.gov.sg live through DataGovSG_IS, so assertions are about behaviour
(counts shrink, order flips, pages advance, files download), not exact values."""
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e
LOAD = 45_000  # live upstream call on every data fetch
COUNT = re.compile(r"^\s*[\d,]+\s*$")


def total(page: Page) -> int:
    value = page.locator(".cm-total-value").first
    expect(value).to_have_text(COUNT, timeout=LOAD)
    return int(value.inner_text().replace(",", "").strip())


def first_company(page: Page) -> str:
    cell = page.locator("table tbody tr").first.locator("td").first
    expect(cell).not_to_be_empty(timeout=LOAD)
    return cell.inner_text().strip()


def search(page: Page, text: str) -> None:
    page.locator("#Input_SearchKey").fill(text)
    page.get_by_role("button", name="Search").click()


@pytest.fixture
def screen(page: Page, ui_url):
    page.goto(f"{ui_url}/Contractors")
    expect(page.get_by_text("Registered contractors", exact=True)).to_be_visible(timeout=LOAD)
    return page


def test_loads_and_shows_results(screen: Page):
    # Public page: no login redirect, real data, a populated table.
    expect(screen).not_to_have_url(re.compile(r"Login"))
    assert total(screen) > 10_000
    expect(screen.locator("table tbody tr")).to_have_count(20, timeout=LOAD)


def test_search_narrows_results(screen: Page):
    everything = total(screen)
    search(screen, "ENGINEERING")
    expect(screen.locator(".cm-total-value").first).not_to_have_text(f"{everything}", timeout=LOAD)
    assert 0 < total(screen) < everything


def test_search_with_punctuation_does_not_error(screen: Page):
    # data.gov.sg rejects punctuation in q (HTTP 409); DataGovSG_IS strips it.
    search(screen, "PTE. LTD.")
    assert total(screen) > 0
    expect(screen.get_by_text(re.compile("rejected|unavailable|unexpected", re.I))).to_have_count(0)


def test_no_match_shows_friendly_message(screen: Page):
    search(screen, "zzqqxx nosuchcontractor")
    expect(screen.get_by_text(re.compile("No contractors match"))).to_be_visible(timeout=LOAD)


def test_sort_by_company_name_toggles(screen: Page):
    default_first = first_company(screen)  # default sort: company_name ascending
    screen.get_by_role("columnheader", name=re.compile("Company Name")).click()
    expect(screen.locator("table tbody tr").first.locator("td").first).not_to_have_text(default_first, timeout=LOAD)


def test_pagination_moves_to_next_page(screen: Page):
    expect(screen.get_by_text(re.compile(r"Showing 1\D+20 of"))).to_be_visible(timeout=LOAD)
    screen.get_by_role("button", name=re.compile("next", re.I)).click()
    expect(screen.get_by_text(re.compile(r"Showing 21\D+40 of"))).to_be_visible(timeout=LOAD)


def test_export_downloads_excel(screen: Page):
    search(screen, "ENGINEERING")
    total(screen)
    with screen.expect_download(timeout=120_000) as dl:
        screen.get_by_role("button", name=re.compile("Export")).click()
    download = dl.value
    assert re.match(r"Registered_Contractors_\d{4}-\d{2}-\d{2}\.xlsx$", download.suggested_filename)
    with open(download.path(), "rb") as fh:
        assert fh.read(2) == b"PK"  # .xlsx is a zip container
