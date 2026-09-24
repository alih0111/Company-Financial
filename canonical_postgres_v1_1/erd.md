# Canonical PostgreSQL Schema v1 — ERD

> Design artifact (Mermaid). هیچ DB ساخته نشده است.

## High-level domain map

```mermaid
erDiagram
    core ||--o{ ingestion : "reports reference"
    core ||--o{ fundamentals : "company/security"
    core ||--o{ market : "security prices"
    ingestion ||--o{ raw : "report versions"
    ingestion ||--o{ fundamentals : "reports"
    core ||--o{ analytics : "company scores"
    auth ||--o{ portfolio : "users"
    portfolio ||--o{ market : "reads prices"
    core ||--o{ portfolio : "securities/assets"
```

## CORE

```mermaid
erDiagram
    companies ||--o{ securities : "1:N"
    companies {
        uuid id PK
        text legal_name
        text display_name
        text normalized_name UK
        bool is_active
        timestamptz created_at
        timestamptz updated_at
    }
    securities {
        uuid id PK
        uuid company_id FK
        bigint tsetmc_ins_code UK
        text codal_symbol
        text isin UK
        text brs_name
        text security_type
        bool is_primary
        bool is_active
        date valid_from
        date valid_to
    }
    securities ||--o{ security_aliases : "1:N"
    security_aliases {
        uuid id PK
        uuid security_id FK
        text alias_type
        text alias_value
        text source
        date valid_from
        date valid_to
    }
    legacy_entity_map {
        uuid id PK
        text source_system
        text source_table
        text legacy_key
        text entity_type
        uuid target_uuid
        text mapping_method
        numeric confidence
    }
```

## INGESTION + RAW

```mermaid
erDiagram
    companies ||--o{ reports : "company_id"
    securities ||--o{ reports : "security_id (nullable)"
    reports ||--o{ report_versions : "1:N"
    report_versions ||--o{ report_payloads : "1:N"
    reports {
        uuid id PK
        uuid company_id FK
        uuid security_id FK
        text source
        text source_report_id
        bigint tracing_no
        int letter_type
        text report_type
        text title
        date period_end_date
        text jalali_period_text
        int fiscal_year
        int fiscal_month
        timestamptz published_at
        text source_url
        timestamptz discovered_at
        timestamptz processed_at
        text processing_status
        int retry_count
        text error_message
        uuid supersedes_report_id FK
    }
    report_versions {
        uuid id PK
        uuid report_id FK
        int version_no
        text content_hash
        text source_url
        timestamptz collected_at
        text parser_version
    }
    report_payloads {
        uuid id PK
        uuid report_version_id FK
        text payload_type
        text content_hash
        text content_text
        jsonb content_json
        text storage_uri
        text mime_type
        bigint byte_size
    }
    sync_state {
        uuid id PK
        text source
        text stream
        timestamptz watermark
        timestamptz last_success_at
    }
    tracked_securities {
        uuid id PK
        uuid security_id FK
        text source
        bool is_active
    }
    runs {
        uuid id PK
        text source
        text job_type
        timestamptz started_at
        timestamptz finished_at
        text status
        int items_seen
        int items_inserted
        int items_updated
        int items_failed
        jsonb metadata
    }
    data_quality_issues {
        uuid id PK
        text entity_type
        uuid entity_id
        text issue_code
        text severity
        timestamptz detected_at
        timestamptz resolved_at
        jsonb details
    }
```

## FUNDAMENTALS

```mermaid
erDiagram
    reports ||--o{ monthly_activities : "1:1"
    reports ||--o{ financial_statements : "1:N by type"
    financial_statements ||--o{ financial_facts : "1:N"
    metric_definitions ||--o{ financial_facts : "metric_code"
    monthly_activities {
        uuid id PK
        uuid company_id FK
        uuid security_id FK
        uuid report_id FK
        uuid report_version_id FK
        date period_end_date
        text jalali_period_text
        int fiscal_year
        int fiscal_month
        numeric production_quantity
        numeric sales_quantity
        text quantity_unit
        numeric sales_amount_rial
        numeric reported_sales_amount
        text reported_currency_unit
        numeric reported_unit_multiplier
    }
    financial_statements {
        uuid id PK
        uuid company_id FK
        uuid report_id FK
        uuid report_version_id FK
        text statement_type
        date period_end_date
        date period_start_date
        int fiscal_year
        int fiscal_month
        int duration_months
        bool is_cumulative
        bool is_audited
        bool is_restated
        text reported_currency_unit
    }
    financial_facts {
        bigint id PK
        uuid statement_id FK
        text metric_code FK
        text row_title
        smallint period_order
        text comparison_type
        numeric reported_value
        text reported_unit
        numeric canonical_value
        text canonical_unit
        bool is_derived_from_source
        text source_row_key
        jsonb metadata
    }
    metric_definitions {
        text metric_code PK
        text statement_type
        text canonical_name
        text display_name_fa
        text expected_unit
    }
```

## MARKET

```mermaid
erDiagram
    securities ||--o{ daily_prices : "1:N"
    securities ||--o{ corporate_actions : "1:N"
    securities ||--o{ vendor_snapshots : "0:N"
    daily_prices {
        bigint id PK
        uuid security_id FK
        date trade_date
        numeric first_price_rial
        numeric open_price_rial
        numeric high_price_rial
        numeric low_price_rial
        numeric closing_price_rial
        numeric last_price_rial
        numeric yesterday_price_rial
        numeric closing_change_rial
        numeric closing_change_percent
        numeric last_change_rial
        numeric last_change_percent
        bigint volume
        numeric trade_value_rial
        bigint trade_count
        bool is_adjusted
        text adjustment_method
        timestamptz adjusted_at
        text source
        text jalali_date_text
    }
    corporate_actions {
        uuid id PK
        uuid security_id FK
        date action_date
        text action_type
        numeric adjustment_factor
        bool is_confirmed
        bool detected_heuristically
        jsonb metadata
    }
    vendor_snapshots {
        uuid id PK
        uuid security_id FK
        uuid company_id FK
        timestamptz captured_at
        text vendor
        text metric_code
        numeric value
        text unit
        jsonb raw_payload
    }
```

## ANALYTICS

```mermaid
erDiagram
    score_runs ||--o{ company_scores : "1:N"
    score_runs ||--o{ factor_scores : "1:N"
    companies ||--o{ company_scores : "company_id"
    companies ||--o{ factor_scores : "company_id"
    companies ||--o{ metric_snapshots : "company_id"
    score_runs {
        uuid id PK
        text score_version
        date as_of_date
        timestamptz started_at
        timestamptz completed_at
        text code_version
        jsonb parameters
        text status
    }
    company_scores {
        bigint id PK
        uuid run_id FK
        uuid company_id FK
        uuid primary_security_id FK
        numeric quant_score
        numeric data_quality_score
        numeric growth_score
        numeric profitability_score
        numeric valuation_score
        numeric market_score
        text score_version
        text input_hash
        jsonb details
    }
    factor_scores {
        bigint id PK
        uuid run_id FK
        uuid company_id FK
        text factor_code
        numeric raw_value
        numeric percentile
        numeric weighted_score
        numeric weight
        jsonb metadata
    }
    metric_snapshots {
        bigint id PK
        date as_of_date
        uuid company_id FK
        uuid primary_security_id FK
        text metric_code
        numeric value
        text unit
        text calculation_version
        timestamptz source_cutoff_at
        jsonb details
    }
```

## AUTH + PORTFOLIO

```mermaid
erDiagram
    users ||--o{ user_view_events : "1:N"
    users ||--o{ portfolios : "user_id"
    portfolios ||--o{ participants : "1:N"
    portfolios ||--o{ accounts : "1:N"
    portfolios ||--o{ positions : "1:N"
    portfolios ||--o{ transactions : "1:N"
    portfolios ||--o{ valuation_snapshots : "1:N"
    participants ||--o{ accounts : "participant_id"
    participants ||--o{ transactions : "participant_id"
    accounts ||--o{ transactions : "account_id"
    assets ||--o{ transactions : "asset_id"
    assets ||--o{ asset_price_snapshots : "1:N"
    securities ||--o{ assets : "security_id (listed asset)"
    users {
        uuid id PK
        citext username UK
        citext email UK
        text password_hash
        bool is_admin
        bool is_active
        timestamptz created_at
        timestamptz updated_at
        timestamptz last_login_at
    }
    portfolios {
        uuid id PK
        uuid user_id FK
        text name
        text portfolio_type
        text base_currency
        numeric initial_capital_rial
        bool is_active
    }
    participants {
        uuid id PK
        uuid portfolio_id FK
        text name
        uuid user_id FK
        int sort_order
        bool is_active
    }
    accounts {
        uuid id PK
        uuid portfolio_id FK
        uuid participant_id FK
        text account_type
        text broker
        text external_account_ref
    }
    assets {
        uuid id PK
        uuid security_id FK
        text asset_type
        text name
        text symbol
        text pricing_source
        numeric commission_rate
        bool is_active
    }
    transactions {
        uuid id PK
        uuid portfolio_id FK
        uuid account_id FK
        uuid participant_id FK
        uuid asset_id FK
        text transaction_type
        date trade_date
        numeric quantity
        numeric price_rial
        numeric gross_amount_rial
        numeric fee_rial
        numeric tax_rial
        numeric net_amount_rial
        text external_ref
        uuid reverses_tx_id FK
        jsonb metadata
    }
    positions {
        uuid portfolio_id PK
        uuid asset_id PK
        numeric quantity
        numeric avg_cost_rial
        numeric cost_basis_rial
        timestamptz as_of_at
    }
    valuation_snapshots {
        uuid id PK
        uuid portfolio_id FK
        date valuation_date
        numeric total_value_rial
        numeric cash_value_rial
        numeric invested_value_rial
        numeric pnl_rial
        numeric return_pct
    }
    asset_price_snapshots {
        uuid id PK
        uuid asset_id FK
        date price_date
        numeric price_rial
        text source
    }
```
