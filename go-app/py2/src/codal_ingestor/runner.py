from __future__ import annotations

import logging
from typing import Literal

from codal_ingestor.collectors.base import ScrapeRequest
from codal_ingestor.collectors.monthly import MonthlyCollector
from codal_ingestor.collectors.profit_loss import ProfitLossCollector
from codal_ingestor.config import get_settings
from codal_ingestor.db import ensure_schema, session_scope
from codal_ingestor.logging_config import configure_logging
from codal_ingestor.repository import ReportRepository


logger = logging.getLogger(__name__)
ReportType = Literal["monthly", "profit-loss"]


def run_scrape(
    *,
    report_type: ReportType,
    company_name: str,
    base_url: str,
    pages: tuple[int, ...],
    row_limit: int,
) -> dict:
    configure_logging(get_settings().log_level)
    ensure_schema()

    request = ScrapeRequest(
        company_name=company_name.strip(),
        base_url=base_url.strip(),
        pages=pages,
        row_limit=row_limit,
    )

    if not request.company_name:
        raise ValueError("company name is required")
    if not request.base_url:
        raise ValueError("base URL is required")
    if not request.pages:
        raise ValueError("at least one page number is required")
    if request.row_limit < 1:
        raise ValueError("row limit must be greater than zero")

    if report_type == "monthly":
        reports = MonthlyCollector().collect(request)
    elif report_type == "profit-loss":
        reports = ProfitLossCollector().collect(request)
    else:
        raise ValueError(f"unsupported report type: {report_type}")

    saved = 0
    unchanged = 0
    failed = 0
    errors: list[str] = []

    for report in reports:
        try:
            with session_scope() as session:
                repository = ReportRepository(session)
                if report_type == "monthly":
                    result = repository.save_monthly(report)
                else:
                    result = repository.save_profit_loss(report)
            if result.status == "unchanged":
                unchanged += 1
            else:
                saved += 1
        except Exception as exc:
            failed += 1
            message = f"{report.period_end_jalali}: {exc}"
            errors.append(message)
            logger.exception("Could not save report: %s", message)

    return {
        "ok": failed == 0,
        "company": request.company_name,
        "reportType": report_type,
        "collected": len(reports),
        "saved": saved,
        "unchanged": unchanged,
        "failed": failed,
        "errors": errors,
    }
