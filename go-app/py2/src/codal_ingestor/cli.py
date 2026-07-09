from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from codal_ingestor.config import get_settings
from codal_ingestor.db import ensure_schema, session_scope
from codal_ingestor.domain import (
    FinancialFactData,
    MonthlyReportData,
    ProfitLossReportData,
    to_decimal,
)
from codal_ingestor.logging_config import configure_logging
from codal_ingestor.repository import ReportRepository
from codal_ingestor.runner import run_scrape


app = typer.Typer(no_args_is_help=True, add_completion=False)
scrape_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(scrape_app, name="scrape")


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise typer.BadParameter("input JSON must be an object")
    return value


def _parse_pages(value: str) -> tuple[int, ...]:
    text = value.strip()
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise typer.BadParameter("pages JSON must be an array")
        pages = tuple(int(item) for item in parsed)
    else:
        pages = tuple(int(item.strip()) for item in text.split(",") if item.strip())
    if not pages or any(page < 1 for page in pages):
        raise typer.BadParameter("pages must contain positive integers")
    return pages


@app.callback()
def callback() -> None:
    configure_logging(get_settings().log_level)


@app.command("init-schema")
def init_schema() -> None:
    ensure_schema()
    _emit({"ok": True, "status": "schema_ready"})


@scrape_app.command("monthly")
def scrape_monthly(
    company_name: Annotated[str, typer.Option("--company-name")],
    base_url: Annotated[str, typer.Option("--base-url")],
    pages: Annotated[str, typer.Option("--pages")] = "1",
    row_limit: Annotated[int, typer.Option("--row-limit", min=1)] = 20,
) -> None:
    _emit(
        run_scrape(
            report_type="monthly",
            company_name=company_name,
            base_url=base_url,
            pages=_parse_pages(pages),
            row_limit=row_limit,
        )
    )


@scrape_app.command("profit-loss")
def scrape_profit_loss(
    company_name: Annotated[str, typer.Option("--company-name")],
    base_url: Annotated[str, typer.Option("--base-url")],
    pages: Annotated[str, typer.Option("--pages")] = "1",
    row_limit: Annotated[int, typer.Option("--row-limit", min=1)] = 20,
) -> None:
    _emit(
        run_scrape(
            report_type="profit-loss",
            company_name=company_name,
            base_url=base_url,
            pages=_parse_pages(pages),
            row_limit=row_limit,
        )
    )


@app.command("ingest-monthly-json")
def ingest_monthly_json(
    input_file: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
) -> None:
    payload = _load_json(input_file)
    report = MonthlyReportData(
        company_name=str(payload["company_name"]),
        period_end_jalali=str(payload["period_end_jalali"]),
        source_url=str(payload["source_url"]),
        production_quantity=to_decimal(payload.get("production_quantity")),
        sales_quantity=to_decimal(payload.get("sales_quantity")),
        sales_amount=to_decimal(payload.get("sales_amount")),
        domestic_sales_amount=to_decimal(payload.get("domestic_sales_amount")),
        export_sales_amount=to_decimal(payload.get("export_sales_amount")),
        currency_unit=str(payload.get("currency_unit", "unknown")),
        quantity_unit=str(payload.get("quantity_unit", "reported_unit")),
        raw_payload=payload,
    )
    with session_scope() as session:
        result = ReportRepository(session).save_monthly(report)
    _emit({"ok": True, "report_id": result.report_id, "status": result.status})


@app.command("ingest-profit-loss-json")
def ingest_profit_loss_json(
    input_file: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
) -> None:
    payload = _load_json(input_file)
    facts_payload = payload.get("facts")
    if not isinstance(facts_payload, list):
        raise typer.BadParameter("facts must be an array")
    facts = tuple(
        FinancialFactData(
            period_order=int(item["period_order"]),
            period_header=str(item["period_header"]),
            metric_code=str(item["metric_code"]),
            value=to_decimal(item.get("value")),
            unit_code=str(item["unit_code"]),
        )
        for item in facts_payload
    )
    report = ProfitLossReportData(
        company_name=str(payload["company_name"]),
        period_end_jalali=str(payload["period_end_jalali"]),
        source_url=str(payload["source_url"]),
        facts=facts,
        raw_payload=payload,
    )
    with session_scope() as session:
        result = ReportRepository(session).save_profit_loss(report)
    _emit({"ok": True, "report_id": result.report_id, "status": result.status})


if __name__ == "__main__":
    app()
