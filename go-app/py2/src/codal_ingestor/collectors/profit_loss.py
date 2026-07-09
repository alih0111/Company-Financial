from __future__ import annotations

import logging

from playwright.sync_api import Page, TimeoutError

from codal_ingestor.collectors.base import ScrapeRequest
from codal_ingestor.collectors.browser import (
    browser_context,
    collect_report_links,
    read_report_date,
    wait_for_angular_stable,
)
from codal_ingestor.domain import ProfitLossReportData, normalize_label
from codal_ingestor.parsers.profit_loss import find_profit_loss_table, parse_profit_loss_html


logger = logging.getLogger(__name__)


class ProfitLossCollector:
    def collect(self, request: ScrapeRequest) -> list[ProfitLossReportData]:
        reports: list[ProfitLossReportData] = []

        with browser_context() as context:
            page = context.pages[0] if context.pages else context.new_page()
            links = collect_report_links(
                page,
                request.base_url,
                request.pages,
                request.row_limit,
            )

            for link in links:
                try:
                    report = self._collect_report(page, request.company_name, link)
                    reports.append(report)
                    logger.info(
                        "Parsed profit/loss report %s - %s",
                        request.company_name,
                        report.period_end_jalali,
                    )
                except Exception as exc:
                    logger.exception("Could not parse profit/loss report %s: %s", link, exc)

        return reports

    def _collect_report(
        self,
        page: Page,
        company_name: str,
        link: str,
    ) -> ProfitLossReportData:
        page.goto(link, wait_until="domcontentloaded", timeout=60_000)
        wait_for_angular_stable(page)
        self._ensure_profit_loss_selected(page)

        try:
            page.wait_for_selector("table.rayanDynamicStatement", timeout=20_000)
        except TimeoutError as exc:
            raise ValueError("financial statement table did not load") from exc

        page.wait_for_timeout(800)
        html = page.content()
        return parse_profit_loss_html(
            html=html,
            company_name=company_name,
            source_url=link,
            report_date=read_report_date(page),
        )

    def _ensure_profit_loss_selected(self, page: Page) -> None:
        if find_profit_loss_table(page.content()) is not None:
            return

        selectors = (
            "select#ctl00_ddlTable",
            "select#ddlTable",
            "select[name*='ddlTable']",
            "select[id*='ddlTable']",
        )
        select_locator = None
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() > 0:
                select_locator = locator.first
                break

        if select_locator is None:
            all_selects = page.locator("select")
            for index in range(all_selects.count()):
                candidate = all_selects.nth(index)
                options = candidate.locator("option")
                option_names = {
                    normalize_label(options.nth(item).inner_text())
                    for item in range(options.count())
                }
                if normalize_label("صورت سود و زیان") in option_names:
                    select_locator = candidate
                    break

        if select_locator is None:
            raise ValueError("profit/loss selector was not found")

        selected_text = ""
        try:
            selected_text = normalize_label(
                select_locator.locator("option:checked").inner_text(timeout=3_000)
            )
        except Exception:
            pass

        if selected_text in {
            normalize_label("صورت سود و زیان"),
            normalize_label("صورت سود و زیان تلفیقی"),
        }:
            return

        target_value = None
        options = select_locator.locator("option")
        for index in range(options.count()):
            option = options.nth(index)
            if normalize_label(option.inner_text()) == normalize_label("صورت سود و زیان"):
                target_value = option.get_attribute("value")
                break

        if target_value is None:
            raise ValueError("profit/loss option was not found")

        select_locator.select_option(value=target_value, timeout=10_000)
        page.wait_for_timeout(2_000)
        wait_for_angular_stable(page)

        if find_profit_loss_table(page.content()) is None:
            raise ValueError("selected table is not a profit/loss statement")
