"""initial schema

Revision ID: 0001_initial
Revises:
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("instrument_code", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_code"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("period_end_jalali", sa.String(length=10), nullable=False),
        sa.Column("period_end_date", sa.Date(), nullable=False),
        sa.Column("current_source_url", sa.Text(), nullable=False),
        sa.Column("current_content_hash", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "report_type", "period_end_jalali", name="uq_reports_company_type_period"),
    )
    op.create_index("ix_reports_company_type_date", "reports", ["company_id", "report_type", "period_end_date"])
    op.create_table(
        "report_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "content_hash", name="uq_report_versions_hash"),
    )
    op.create_table(
        "monthly_activities",
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_quantity", sa.Numeric(30, 4), nullable=True),
        sa.Column("sales_quantity", sa.Numeric(30, 4), nullable=True),
        sa.Column("sales_amount", sa.Numeric(30, 4), nullable=True),
        sa.Column("domestic_sales_amount", sa.Numeric(30, 4), nullable=True),
        sa.Column("export_sales_amount", sa.Numeric(30, 4), nullable=True),
        sa.Column("currency_unit", sa.String(length=16), nullable=False),
        sa.Column("quantity_unit", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id"),
    )
    op.create_table(
        "financial_facts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_order", sa.SmallInteger(), nullable=False),
        sa.Column("period_header", sa.Text(), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Numeric(30, 4), nullable=True),
        sa.Column("unit_code", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "period_order", "metric_code", name="uq_financial_fact_metric"),
    )
    op.create_index("ix_financial_facts_report_metric", "financial_facts", ["report_id", "metric_code"])


def downgrade() -> None:
    op.drop_index("ix_financial_facts_report_metric", table_name="financial_facts")
    op.drop_table("financial_facts")
    op.drop_table("monthly_activities")
    op.drop_table("report_versions")
    op.drop_index("ix_reports_company_type_date", table_name="reports")
    op.drop_table("reports")
    op.drop_table("companies")
