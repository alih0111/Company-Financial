# v1.1 → v1.2 Change Log (Final Hardening)

> نسخه‌های v1 و v1.1 دست‌نخورده‌اند. هیچ DDL/migration اجرا نشده. هیچ production code تغییر نکرده.

| # | موضوع | v1.1 | v1.2 | دلیل |
| --- | --- | --- | --- | --- |
| 1 | Fetch vs Parse | `report_versions` شامل `parser_version`؛ re-parse → version جدید (تناقض با content_hash) | `report_versions` فقط محتوا (بدون parser_version)؛ `parse_runs` جدید (1..N) | fetch/محتوای یکسان می‌تواند با parserهای متعدد parse شود |
| 2 | Normalized→parse_run | اتصال به report_version | `parse_run_id` NOT NULL + composite FK زنجیره؛ uniqueness parse-aware | traceability کامل report→version→parse→output |
| 3 | Legacy migration | synthetic report_version | synthetic report_version + synthetic parse_run (`legacy_sqlserver`) | اتصال normalized به parse_run |
| 4 | Immutability | مستند، بدون trigger (جز raw/facts/transactions) | trigger روی report_versions و monthly_activities و financial_statements؛ parse_runs lifecycle-only | DB-level واقعی |
| 5 | Supersede cycles | فقط self-check | trigger recursive CTE (۲فره/NFره) + قفل `source`/`source_report_id` | جلوگیری از cycle و drift |
| 6 | Market revisioning | یک table با UNIQUE(security,date) + provenance (history واقعی نبود) | `price_observations` append-only + `daily_prices` view | نگه‌داشت نسخه‌های قبلی برای backtest |
| 7 | PIT cutoff | فقط metric_snapshots | `score_runs.source_cutoff_at` + قرارداد `collected_at <= cutoff` | backtest بدون look-ahead |
| 8 | Analytics security FK | composite RESTRICT + باقی‌ماندن FK ساده SET NULL (conflict) | فقط composite RESTRICT | یک policy واحد |
| 9 | vendor_snapshots | FK ساده nullable | CHECK (security⇒company) + composite FK RESTRICT | consistency |
| 10 | Initial capital | `portfolios.initial_capital_rial` | حذف؛ `opening_cash` در ledger | ledger تنها منبع accounting |
| 11 | Commission | `assets.commission_rate` | حذف؛ `transactions.fee_rial` منبع | کارمزد ویژگی asset نیست |
| 12 | Ledger date | `trade_date NOT NULL` برای همه | `effective_date NOT NULL` + `trade_date NULL` (الزامی فقط buy/sell) | opening بدون تاریخ خرید جعلی |
| 13 | Opening cost | legacy cost در JSON metadata | `cost_basis_rial` ساختاریافته (الزامی برای opening_position) | rebuild position بدون parse JSON |
| 14 | Accounting semantics | ضمنی | `quantity_delta`/`cash_delta_rial` علامت‌دار + CHECK + queryهای قطعی | cash/position قابل محاسبه‌ی قطعی |
| 15 | Reversal | فقط reverses_tx_id | `transaction_type='reversal'` + trigger معکوس‌ساز اجباری | اثر واقعی خنثی شود |
| 16 | Account در ledger | nullable | `account_id NOT NULL` + account synthetic برای legacy | reconcile cash |
| 17 | Asset metadata | name/symbol اجباری | nullable برای security-linked + view `assets_resolved` | حذف duplicate mutable metadata |
| 18 | Analytics immutability | مستند | trigger append-only + lifecycle score_runs | reproducibility |
| 19 | SQLAlchemy doc | stale refs | sync کامل با v1.2 | consistency |
| 20 | Integrity tests | ۲۷ | **۵۲** (DB-level) | پوشش کامل |
| 21 | Market PIT example | — | مثال عددی + SQL | مستند |
| 22 | Ledger examples | — | مثال عددی cash/position/avg cost | مستند |
| 23 | Static review | — | cross-check همه‌ی اسناد/DDL | نبود تناقض |

## فایل‌های تغییر‌یافته/جدید
- SQL بازنویسی: `020_ingestion.sql`, `040_fundamentals.sql`, `050_market.sql`, `070_portfolio.sql`, `080_analytics.sql`, `090_indexes.sql`, `030_raw.sql` (header).
- Docs: `schema.md`, `erd.md`, `sqlalchemy_model_plan.md`, `migration_plan.md`, `validation_plan.md`, `integrity_test_plan.md`, `legacy_to_v1_mapping.md`, `README.md`.
- جدید: `v1_1_to_v1_2_changes.md`.
- بدون تغییر ساختاری: `001_extensions.sql`, `010_core.sql`, `060_auth.sql`, `miandore2_fact_mapping.md`, `v37_compatibility.md`.
