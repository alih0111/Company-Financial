from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    instrument_code: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    reports: Mapped[list[Report]] = relationship(back_populates="company")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "report_type",
            "period_end_jalali",
            name="uq_reports_company_type_period",
        ),
        Index("ix_reports_company_type_date", "company_id", "report_type", "period_end_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_end_jalali: Mapped[str] = mapped_column(String(10), nullable=False)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    current_source_url: Mapped[str] = mapped_column(Text, nullable=False)
    current_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    company: Mapped[Company] = relationship(back_populates="reports")
    versions: Mapped[list[ReportVersion]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    monthly_activity: Mapped[MonthlyActivity | None] = relationship(
        back_populates="report", cascade="all, delete-orphan", uselist=False
    )
    financial_facts: Mapped[list[FinancialFact]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class ReportVersion(Base):
    __tablename__ = "report_versions"
    __table_args__ = (
        UniqueConstraint("report_id", "content_hash", name="uq_report_versions_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    report: Mapped[Report] = relationship(back_populates="versions")


class MonthlyActivity(Base):
    __tablename__ = "monthly_activities"

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    production_quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    sales_quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    sales_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    domestic_sales_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    export_sales_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    currency_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    quantity_unit: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")

    report: Mapped[Report] = relationship(back_populates="monthly_activity")


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "period_order", "metric_code", name="uq_financial_fact_metric"
        ),
        Index("ix_financial_facts_report_metric", "report_id", "metric_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    period_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_header: Mapped[str] = mapped_column(Text, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(30, 4))
    unit_code: Mapped[str] = mapped_column(String(32), nullable=False)

    report: Mapped[Report] = relationship(back_populates="financial_facts")
