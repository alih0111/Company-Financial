from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Page, Playwright, TimeoutError, sync_playwright

from codal_ingestor.config import get_settings
from codal_ingestor.parsers.common import find_jalali_date


logger = logging.getLogger(__name__)


def with_page_number(base_url: str, page_number: int) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["PageNumber"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@contextmanager
def browser_context() -> Iterator[BrowserContext]:
    settings = get_settings()
    profile_dir = settings.resolved_profile_dir
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir)
        try:
            yield context
        finally:
            context.close()


def _launch_context(playwright: Playwright, profile_dir: Path) -> BrowserContext:
    settings = get_settings()
    options: dict = {
        "user_data_dir": str(profile_dir),
        "headless": settings.playwright_headless,
        "viewport": {"width": 1366, "height": 768},
        "args": [
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }

    binary = settings.resolved_chromium_binary
    if binary is not None:
        if not binary.exists():
            raise FileNotFoundError(f"Chromium executable not found: {binary}")
        options["executable_path"] = str(binary)

    return playwright.chromium.launch_persistent_context(**options)


def wait_for_angular_stable(page: Page, timeout: int = 15_000) -> None:
    try:
        page.wait_for_function(
            """
            () => {
                if (!window.getAllAngularTestabilities) return true;
                return window.getAllAngularTestabilities().every(t => t.isStable());
            }
            """,
            timeout=timeout,
        )
    except TimeoutError:
        logger.warning("Angular stability wait timed out; continuing")


def collect_report_links(page: Page, base_url: str, pages: tuple[int, ...], row_limit: int) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    for page_number in pages:
        current_url = with_page_number(base_url, page_number)
        logger.info("Opening Codal list page %s", current_url)
        try:
            page.goto(current_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector("tbody.scrollContent tr", timeout=25_000)
            page.wait_for_timeout(2_000)
        except TimeoutError:
            logger.warning("Report list did not load on page %s", page_number)
            continue

        rows = page.locator("tbody.scrollContent tr")
        count = min(rows.count(), row_limit)
        for index in range(count):
            row = rows.nth(index)
            candidates = row.locator("td:nth-child(4) a")
            if candidates.count() == 0:
                candidates = row.locator("a[href]")

            for anchor_index in range(candidates.count()):
                href = candidates.nth(anchor_index).get_attribute("href")
                if not href:
                    continue
                absolute = urljoin("https://www.codal.ir", href)
                if absolute in seen:
                    continue
                seen.add(absolute)
                links.append(absolute)
                break

    logger.info("Found %s unique report links", len(links))
    return links


def read_report_date(page: Page) -> str | None:
    selectors = (
        "#ctl00_lblPeriodEndToDate",
        "#lblPeriodEndToDate",
        "[id*='lblPeriodEndToDate']",
    )
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() == 0:
                continue
            value = find_jalali_date(locator.first.inner_text(timeout=3_000))
            if value:
                return value
        except Exception:
            continue
    return None
