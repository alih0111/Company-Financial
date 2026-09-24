-- ============================================================================
-- 040_fundamentals.sql  —  monthly activities, financial statements/facts, metric dict
-- v1.2 (final hardening). DO NOT EXECUTE in this phase.
--
-- v1.2 chain: report -> report_version (fetch) -> parse_run (parser) -> normalized.
-- Normalized outputs carry parse_run_id (NOT NULL) + report_version_id + report_id,
-- kept denormalized for query ergonomics but chain-consistent via composite FKs.
-- All normalized tables are append-only (DB-enforced). Re-parse => new parse_run
-- => new rows.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- fundamentals.metric_definitions
-- ----------------------------------------------------------------------------
CREATE TABLE fundamentals.metric_definitions (
    metric_code     text        PRIMARY KEY,
    statement_type  text,
    canonical_name  text        NOT NULL,
    display_name_fa text,
    expected_unit   text,
    description     text,
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT metric_definitions_statement_type_chk CHECK (statement_type IS NULL OR statement_type IN
        ('income_statement','balance_sheet','cash_flow','comprehensive_income','equity_changes','monthly_activity'))
);

CREATE TRIGGER trg_metric_definitions_updated_at
    BEFORE UPDATE ON fundamentals.metric_definitions
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- ----------------------------------------------------------------------------
-- fundamentals.monthly_activities
-- Legacy: Value1=production qty, Value2=sales qty, Value3=sales revenue (million IRR)
-- ----------------------------------------------------------------------------
CREATE TABLE fundamentals.monthly_activities (
    id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id             uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    security_id            uuid,
    report_id              uuid        NOT NULL REFERENCES ingestion.reports(id) ON DELETE RESTRICT,
    report_version_id      uuid        NOT NULL,
    -- v1.2 (item 2): parser execution that produced this output.
    parse_run_id           uuid        NOT NULL,
    period_end_date        date        NOT NULL,
    jalali_period_text     text,
    fiscal_year            integer,
    fiscal_month           integer,
    production_quantity    numeric(30,4),
    sales_quantity         numeric(30,4),
    quantity_unit          text,
    sales_amount_rial      numeric(30,4),
    reported_sales_amount  numeric(30,4),
    reported_currency_unit text,
    reported_unit_multiplier numeric(24,4),
    created_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT monthly_activities_fiscal_month_chk CHECK (fiscal_month IS NULL OR (fiscal_month BETWEEN 1 AND 12)),
    CONSTRAINT monthly_activities_currency_unit_chk CHECK (reported_currency_unit IS NULL OR reported_currency_unit IN
        ('rial','thousand_rial','million_rial','unknown')),
    CONSTRAINT monthly_activities_multiplier_chk CHECK (reported_unit_multiplier IS NULL OR reported_unit_multiplier > 0),
    -- v1.2: full, chain-consistent integrity (items 1,2,5)
    CONSTRAINT monthly_activities_version_report_fk FOREIGN KEY (report_version_id, report_id)
        REFERENCES ingestion.report_versions(id, report_id) ON DELETE RESTRICT,
    CONSTRAINT monthly_activities_parse_version_fk FOREIGN KEY (parse_run_id, report_version_id)
        REFERENCES ingestion.parse_runs(id, report_version_id) ON DELETE RESTRICT,
    CONSTRAINT monthly_activities_security_company_fk FOREIGN KEY (security_id, company_id)
        REFERENCES core.securities(id, company_id) ON DELETE RESTRICT,
    -- v1.2.1 (item 3): company must match the parent report's company.
    CONSTRAINT monthly_activities_report_company_fk FOREIGN KEY (report_id, company_id)
        REFERENCES ingestion.reports(id, company_id) ON DELETE RESTRICT
);

-- One normalized monthly output per parse run (parse-aware uniqueness).
CREATE UNIQUE INDEX uq_monthly_activities_parse_run ON fundamentals.monthly_activities (parse_run_id);
CREATE INDEX ix_monthly_activities_report          ON fundamentals.monthly_activities (report_id);
CREATE INDEX ix_monthly_activities_version         ON fundamentals.monthly_activities (report_version_id);
CREATE INDEX ix_monthly_activities_company_period  ON fundamentals.monthly_activities (company_id, period_end_date DESC);
CREATE INDEX ix_monthly_activities_security        ON fundamentals.monthly_activities (security_id) WHERE security_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- fundamentals.financial_statements
-- ----------------------------------------------------------------------------
CREATE TABLE fundamentals.financial_statements (
    id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id             uuid        NOT NULL REFERENCES core.companies(id) ON DELETE RESTRICT,
    report_id              uuid        NOT NULL REFERENCES ingestion.reports(id) ON DELETE RESTRICT,
    report_version_id      uuid        NOT NULL,
    parse_run_id           uuid        NOT NULL,
    statement_type         text        NOT NULL,
    period_end_date        date        NOT NULL,
    period_start_date      date,
    fiscal_year            integer,
    fiscal_month           integer,
    duration_months        integer,
    is_cumulative          boolean,
    is_audited             boolean,
    is_restated            boolean     NOT NULL DEFAULT false,
    reported_currency_unit text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT financial_statements_type_chk CHECK (statement_type IN
        ('income_statement','balance_sheet','cash_flow','comprehensive_income','equity_changes')),
    CONSTRAINT financial_statements_fiscal_month_chk CHECK (fiscal_month IS NULL OR (fiscal_month BETWEEN 1 AND 12)),
    CONSTRAINT financial_statements_duration_chk CHECK (duration_months IS NULL OR duration_months > 0),
    CONSTRAINT financial_statements_period_chk CHECK (period_start_date IS NULL OR period_end_date >= period_start_date),
    CONSTRAINT financial_statements_version_report_fk FOREIGN KEY (report_version_id, report_id)
        REFERENCES ingestion.report_versions(id, report_id) ON DELETE RESTRICT,
    CONSTRAINT financial_statements_parse_version_fk FOREIGN KEY (parse_run_id, report_version_id)
        REFERENCES ingestion.parse_runs(id, report_version_id) ON DELETE RESTRICT,
    -- v1.2.1 (item 3): company must match the parent report's company.
    CONSTRAINT financial_statements_report_company_fk FOREIGN KEY (report_id, company_id)
        REFERENCES ingestion.reports(id, company_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_financial_statements_parse_type
    ON fundamentals.financial_statements (parse_run_id, statement_type);
CREATE INDEX ix_financial_statements_report
    ON fundamentals.financial_statements (report_id);
CREATE INDEX ix_financial_statements_version
    ON fundamentals.financial_statements (report_version_id);
CREATE INDEX ix_financial_statements_company_period
    ON fundamentals.financial_statements (company_id, period_end_date DESC);
CREATE INDEX ix_financial_statements_type_period
    ON fundamentals.financial_statements (statement_type, period_end_date DESC);

-- ----------------------------------------------------------------------------
-- fundamentals.financial_facts   (generic, immutable)
-- Product1/2/3 (legacy mixed-scale) MUST NOT appear here.
-- ----------------------------------------------------------------------------
CREATE TABLE fundamentals.financial_facts (
    id                    bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    statement_id          uuid        NOT NULL REFERENCES fundamentals.financial_statements(id) ON DELETE RESTRICT,
    metric_code           text        NOT NULL REFERENCES fundamentals.metric_definitions(metric_code) ON DELETE RESTRICT,
    row_title             text,
    period_order          smallint    NOT NULL,
    comparison_type       text,
    reported_value        numeric(30,6),
    reported_unit         text,
    canonical_value       numeric(30,6),
    canonical_unit        text,
    is_derived_from_source boolean    NOT NULL DEFAULT false,
    source_row_key        text,
    metadata              jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT financial_facts_period_order_chk CHECK (period_order >= 1),
    CONSTRAINT financial_facts_comparison_type_chk CHECK (comparison_type IS NULL OR comparison_type IN
        ('current','prior_year_same_period','prior_fiscal_year','restated','audited','other'))
);

CREATE UNIQUE INDEX uq_financial_facts_metric
    ON fundamentals.financial_facts (statement_id, metric_code, period_order);
CREATE INDEX ix_financial_facts_metric_lookup ON fundamentals.financial_facts (metric_code);
CREATE INDEX ix_financial_facts_statement     ON fundamentals.financial_facts (statement_id);

-- ----------------------------------------------------------------------------
-- Append-only enforcement (v1.2 item 4): normalized data cannot be mutated.
-- Re-parse => new parse_run + new rows (never UPDATE).
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fundamentals.prevent_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'fundamentals.% is append-only (attempted %)', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE TRIGGER trg_monthly_activities_immutable
    BEFORE UPDATE OR DELETE ON fundamentals.monthly_activities
    FOR EACH ROW EXECUTE FUNCTION fundamentals.prevent_mutation();

CREATE TRIGGER trg_financial_statements_immutable
    BEFORE UPDATE OR DELETE ON fundamentals.financial_statements
    FOR EACH ROW EXECUTE FUNCTION fundamentals.prevent_mutation();

CREATE TRIGGER trg_financial_facts_immutable
    BEFORE UPDATE OR DELETE ON fundamentals.financial_facts
    FOR EACH ROW EXECUTE FUNCTION fundamentals.prevent_mutation();
