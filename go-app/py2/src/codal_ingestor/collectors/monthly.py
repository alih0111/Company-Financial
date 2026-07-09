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
from codal_ingestor.domain import MonthlyReportData
from codal_ingestor.parsers.monthly import parse_monthly_html


logger = logging.getLogger(__name__)


class MonthlyCollector:
    def collect(self, request: ScrapeRequest) -> list[MonthlyReportData]:
        reports: list[MonthlyReportData] = []

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
                        "Parsed monthly report %s - %s",
                        request.company_name,
                        report.period_end_jalali,
                    )
                except Exception as exc:
                    logger.exception("Could not parse monthly report %s: %s", link, exc)

        return reports

    def _collect_report(
        self,
        page: Page,
        company_name: str,
        link: str,
    ) -> MonthlyReportData:
        page.goto(link, wait_until="domcontentloaded", timeout=60_000)
        wait_for_angular_stable(page)
        try:
            page.wait_for_selector("table.rayanDynamicStatement", timeout=20_000)
        except TimeoutError as exc:
            raise ValueError("monthly statement table did not load") from exc

        page.wait_for_timeout(800)
        return parse_monthly_html(
            html=page.content(),
            company_name=company_name,
            source_url=link,
            report_date=read_report_date(page),
        )
