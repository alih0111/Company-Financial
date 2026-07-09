from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from codal_ingestor.domain import (
    MonthlyReportData,
    ProfitLossReportData,
    canonical_payload,
    content_hash,
    jalali_to_gregorian,
    normalize_company_name,
)
from codal_ingestor.models import (
    Company,
    FinancialFact,
    MonthlyActivity,
    Report,
    ReportVersion,
)


@dataclass(frozen=True, slots=True)
class SaveResult:
    report_id: str
    status: str
    content_hash: str


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_monthly(self, data: MonthlyReportData) -> SaveResult:
        company_id = self._upsert_company(data.company_name)
        payload = canonical_payload(data)
        digest = content_hash(payload)
        report, changed = self._upsert_report(
            company_id=company_id,
            report_type="monthly_activity",
            period_end_jalali=data.period_end_jalali,
            source_url=data.source_url,
            digest=digest,
            payload=payload,
        )
        if not changed:
            return SaveResult(str(report.id), "unchanged", digest)

        statement = insert(MonthlyActivity).values(
            report_id=report.id,
            production_quantity=data.production_quantity,
            sales_quantity=data.sales_quantity,
            sales_amount=data.sales_amount,
            domestic_sales_amount=data.domestic_sales_amount,
            export_sales_amount=data.export_sales_amount,
            currency_unit=data.currency_unit,
            quantity_unit=data.quantity_unit,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[MonthlyActivity.report_id],
            set_={
                "production_quantity": statement.excluded.production_quantity,
                "sales_quantity": statement.excluded.sales_quantity,
                "sales_amount": statement.excluded.sales_amount,
                "domestic_sales_amount": statement.excluded.domestic_sales_amount,
                "export_sales_amount": statement.excluded.export_sales_amount,
                "currency_unit": statement.excluded.currency_unit,
                "quantity_unit": statement.excluded.quantity_unit,
            },
        )
        self.session.execute(statement)
        return SaveResult(str(report.id), "saved", digest)

    def save_profit_loss(self, data: ProfitLossReportData) -> SaveResult:
        company_id = self._upsert_company(data.company_name)
        payload = canonical_payload(data)
        digest = content_hash(payload)
        report, changed = self._upsert_report(
            company_id=company_id,
            report_type="profit_loss",
            period_end_jalali=data.period_end_jalali,
            source_url=data.source_url,
            digest=digest,
            payload=payload,
        )
        if not changed:
            return SaveResult(str(report.id), "unchanged", digest)

        self.session.execute(delete(FinancialFact).where(FinancialFact.report_id == report.id))
        self.session.add_all(
            [
                FinancialFact(
                    report_id=report.id,
                    period_order=fact.period_order,
                    period_header=fact.period_header,
                    metric_code=fact.metric_code,
                    value=fact.value,
                    unit_code=fact.unit_code,
                )
                for fact in data.facts
            ]
        )
        return SaveResult(str(report.id), "saved", digest)

    def _upsert_company(self, company_name: str):
        normalized_name = normalize_company_name(company_name)
        statement = insert(Company).values(name=company_name, normalized_name=normalized_name)
        statement = statement.on_conflict_do_update(
            index_elements=[Company.normalized_name],
            set_={"name": statement.excluded.name, "is_active": True},
        ).returning(Company.id)
        return self.session.execute(statement).scalar_one()

    def _upsert_report(
        self,
        *,
        company_id,
        report_type: str,
        period_end_jalali: str,
        source_url: str,
        digest: str,
        payload: dict,
    ) -> tuple[Report, bool]:
        existing = self.session.scalar(
            select(Report).where(
                Report.company_id == company_id,
                Report.report_type == report_type,
                Report.period_end_jalali == period_end_jalali,
            )
        )
        if existing is not None and existing.current_content_hash == digest:
            return existing, False

        statement = insert(Report).values(
            company_id=company_id,
            report_type=report_type,
            period_end_jalali=period_end_jalali,
            period_end_date=jalali_to_gregorian(period_end_jalali),
            current_source_url=source_url,
            current_content_hash=digest,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_reports_company_type_period",
            set_={
                "period_end_date": statement.excluded.period_end_date,
                "current_source_url": statement.excluded.current_source_url,
                "current_content_hash": statement.excluded.current_content_hash,
            },
        ).returning(Report.id)
        report_id = self.session.execute(statement).scalar_one()
        report = self.session.get(Report, report_id)
        if report is None:
            raise RuntimeError("report upsert did not return a persisted report")

        version_statement = insert(ReportVersion).values(
            report_id=report.id,
            source_url=source_url,
            content_hash=digest,
            raw_payload=payload,
        )
        version_statement = version_statement.on_conflict_do_nothing(
            constraint="uq_report_versions_hash"
        )
        self.session.execute(version_statement)
        return report, True
