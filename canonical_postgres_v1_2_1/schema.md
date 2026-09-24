# Canonical PostgreSQL Schema v1.2 — Schema Specification

> Final hardening artifact + pre-execution patch. **هیچ DDL اجرا نشده است.**
> تغییرات v1.1→v1.2 در `v1_1_to_v1_2_changes.md` و patch نهایی در `v1_2_to_v1_2_1_changes.md`.

## Addendum v1.2.1 (patch)
- **Report→Company integrity:** `ingestion.reports` دارای `UNIQUE(id, company_id)` است؛ `monthly_activities` و `financial_statements` composite FK `(report_id, company_id) → reports(id, company_id)` دارند. (جدول `financial_statements` چون `security_id` ندارد، فقط این FK را دارد.)
- **Terminal lifecycles:** `parse_runs` فقط `running→completed|failed|unsupported` و بعد terminal؛ `score_runs` فقط `running→completed|failed|partial` و بعد terminal. `finished_at`/`completed_at` با status سازگار است (trigger).
- **Reversal-aware reconstruction:** view `portfolio.effective_transactions` (originalsِ reversed و reversalها حذف می‌شوند). reversal حالا `quantity_delta`, `cash_delta_rial`, `cost_basis_rial` را negate و `participant_id`, `account_id`, `asset_id`, `portfolio_id` را inherit می‌کند.
- **Quantity derived:** `transactions.quantity` ستون **generated** `= abs(quantity_delta)` است (نمی‌تواند drift کند).
- **Price dedup scoped:** `UNIQUE(security_id, trade_date, source, price_series, observation_hash)` — نه global.
- **daily_prices selection:** deterministic: `price_series='adjusted'`، بیشترین `collected_at`، tie-break با id.

## زنجیره‌ی provenance (نهایی)
```
ingestion.reports
   └─ ingestion.report_versions      (FETCH/content version, append-only)
        └─ ingestion.parse_runs      (parser execution, 1..N)
             ├─ fundamentals.monthly_activities
             ├─ fundamentals.financial_statements
             │    └─ fundamentals.financial_facts
             └─ ...
```
هر normalized row دارای `parse_run_id` (NOT NULL) + `report_version_id` + `report_id` است؛ سازگاری زنجیره با composite FK تضمین می‌شود.

## ۱) Fetch vs Parse (تفکیک)
- `ingestion.report_versions` فقط محتوا: `report_id, version_no, content_hash, source_url, collected_at, created_at`. **`parser_version` حذف شد.**
- `ingestion.parse_runs`: `id, report_version_id, parser_name, parser_version, code_version, started_at, finished_at, status, parameters, error_message, created_at`.
- یک report_version → چند parse_run. UNIQUE جزئی: یک parse_run **completed** per `(report_version_id, parser_name, parser_version)`.
- dedup محتوای fetch: `UNIQUE(report_id, content_hash)` (محتوای یکسان دوباره ذخیره نمی‌شود).

## ۲) Normalized به parse_run
- `monthly_activities`: `parse_run_id NOT NULL`؛ `UNIQUE(parse_run_id)`.
- `financial_statements`: `parse_run_id NOT NULL`؛ `UNIQUE(parse_run_id, statement_type)`.
- denormalized `report_version_id`/`report_id` باقی می‌مانند؛ FKها:
  `(parse_run_id, report_version_id) → parse_runs(id, report_version_id)` و
  `(report_version_id, report_id) → report_versions(id, report_id)`.
  → سه شناسه نمی‌توانند به chainهای متفاوت اشاره کنند.

## ۳) Migration legacy
برای هر report: یک synthetic `report_version` (provenance موجود) و یک synthetic `parse_run` (`parser_name='legacy_sqlserver'`, `parser_version='legacy_import_v1'`, `status='completed'`) ساخته می‌شود. همه‌ی normalized داده‌ها به آن parse_run وصل می‌شوند.

## ۴) Immutability واقعی (DB-enforced)
trigger `BEFORE UPDATE OR DELETE` برای:
`ingestion.report_versions`, `raw.report_payloads`, `fundamentals.monthly_activities`,
`fundamentals.financial_statements`, `fundamentals.financial_facts`.
`ingestion.parse_runs` فقط lifecycle ستون‌ها (`status, finished_at, error_message`) را می‌تواند تغییر دهد؛ identity (`report_version_id, parser_name, parser_version, code_version, started_at, parameters`) frozen. Re-parse = parse_run جدید + rows جدید.

## ۵) Supersedes cycle detection
`ingestion.reports.supersedes_report_id` self-FK (RESTRICT) +:
- CHECK عدم self-supersede.
- trigger `check_supersede_cycle` با recursive CTE که cycleهای ۲فره/NFره را رد می‌کند.
- trigger `prevent_report_identity_change`: تغییر `source`/`source_report_id` بعد از insert ممنوع.

## ۶) Market price revisioning (واقعی)
- **`market.price_observations`** = append-only source of truth؛ چند نسخه برای یک `(security,trade_date)` مجاز.
  - فیلدهای قیمت/حجم + `price_series, adjustment_method, adjustment_version, provenance, source, collected_at, observation_hash`.
  - dedup: `UNIQUE(observation_hash)` (observation یکسان دوباره ذخیره نمی‌شود).
  - immutability trigger.
- **`market.daily_prices`** = **VIEW** که latest canonical (adjusted) observation هر `(security_id, trade_date)` را برمی‌گرداند (مرتب‌سازی `collected_at DESC, id DESC`). API ساده از view می‌خواند؛ نسخه‌های قدیمی برای backtest باقی می‌مانند.
- هیچ نسخه‌ی قبلی silent overwrite نمی‌شود.

### ۷) Point-in-time market selection
`analytics.score_runs.source_cutoff_at timestamptz NOT NULL` اضافه شد (سازگار با `metric_snapshots.source_cutoff_at`).
Backtest فقط observationهای `collected_at <= source_cutoff_at` را می‌بیند.

**مثال عددی (item 21):** security X، trade_date D:
| observation | collected_at | adjustment_version | closing_price_rial |
| --- | --- | --- | --- |
| A | T1 | v1 | 100 |
| B | T2 | v2 | 80 |

با `T1 < cutoff < T2` → 100 ؛ با `cutoff > T2` → 80.
```sql
-- Point-in-time closing price
SELECT DISTINCT ON (security_id, trade_date)
       security_id, trade_date, closing_price_rial, adjustment_version, collected_at
FROM market.price_observations
WHERE security_id = :sec
  AND trade_date  = :d
  AND collected_at <= :cutoff          -- look-ahead guard
ORDER BY security_id, trade_date, collected_at DESC, id DESC;

-- Latest (API) price via canonical view
SELECT * FROM market.daily_prices WHERE security_id = :sec ORDER BY trade_date DESC LIMIT 1;
```

## ۸) Analytics security FK (policy واحد)
- `company_scores.primary_security_id` و `metric_snapshots.primary_security_id`: فقط **composite FK `(primary_security_id, company_id) → securities(id, company_id) ON DELETE RESTRICT`**.
- FK ساده‌ی `SET NULL` حذف شد (conflict معنایی). securityهای referenced به‌صورت فیزیکی حذف نمی‌شوند.

## ۹) vendor_snapshots
- CHECK: اگر `security_id` مقدار دارد، `company_id` هم باید مقدار داشته باشد.
- composite FK `(security_id, company_id) → securities(id, company_id)` (RESTRICT) + FK `company_id → companies` (RESTRICT).

## ۱۰) Portfolio initial capital
`portfolios.initial_capital_rial` **حذف شد**. منبع accounting فقط ledger است؛ سرمایه‌ی اولیه (paper) = یک `opening_cash` transaction.
(اگر مقدار فقط config است، در آینده domain جدا؛ فعلاً لازم نیست.)

## ۱۱) Commission
`assets.commission_rate` **حذف شد**. کارمزد واقعی در `transactions.fee_rial` (source of truth). `portfolio.fee_schedules` در v1.2 ساخته **نمی‌شود** (ضد over-engineering).

## ۱۲) Universal ledger date
- `effective_date date NOT NULL` برای همه‌ی events.
- `trade_date date NULL` فقط برای market events (`buy`/`sell` الزامی؛ سایر انواع بدون trade_date).
- opening migration: `effective_date = migration/as-of date`، `trade_date = NULL`؛ provenance در `metadata`.

## ۱۳) Opening cost basis (structured)
`transactions.cost_basis_rial numeric(30,4)` (nullable)؛ برای `opening_position` **الزامی** (CHECK). `metadata` فقط provenance.

## ۱۴) Ledger accounting semantics (قطعی)
هر ردیف دو effect علامت‌دار دارد: `quantity_delta` و `cash_delta_rial`.
| type | quantity_delta | cash_delta_rial |
| --- | --- | --- |
| buy | > 0 | < 0 |
| sell | < 0 | > 0 |
| deposit | 0 | > 0 |
| opening_cash | 0 | > 0 |
| withdrawal | 0 | < 0 |
| fee / tax | 0 | < 0 |
| dividend | 0 | > 0 |
| opening_position | > 0 | 0 |
| transfer_in/out, adjustment, reversal | (trigger/حالت) | (trigger/حالت) |

**Queryهای قطعی:**
```sql
-- current cash (per portfolio, per account)
SELECT account_id, SUM(cash_delta_rial) AS cash_balance_rial
FROM portfolio.transactions
WHERE portfolio_id = :p
GROUP BY account_id;

-- current position quantity (per portfolio, per asset)
SELECT asset_id, SUM(quantity_delta) AS quantity
FROM portfolio.transactions
WHERE portfolio_id = :p
GROUP BY asset_id;
```

### مثال عددی (item 22)
Ledger:
| # | type | asset | quantity_delta | cash_delta_rial | cost_basis_rial |
| --- | --- | --- | --- | --- | --- |
| 1 | opening_cash | – | 0 | +100,000,000 | – |
| 2 | buy | A | +100 | −20,000,000 | – |
| 3 | buy | A | +50 | −12,000,000 | – |
| 4 | sell | A | −30 | +8,400,000 | – |

Results:
- cash = 100,000,000 − 20,000,000 − 12,000,000 + 8,400,000 = **76,400,000 ریال**
- qty(A) = 100 + 50 − 30 = **120 سهم**
- cost of held = (20,000,000 + 12,000,000) = 32,000,000 (برای 150 خریداری‌شده) → avg = 213,333.33
  avg_cost_rial = 32,000,000 / 150 = **213,333.33**؛ cost_basis موجود = 213,333.33 × 120 = **25,600,000**.
- برای `opening_position`: cost_basis_rial مستقیماً ورودی است و در همان average مشارکت می‌کند.

## ۱۵) Reversal (v1.2.1)
- `transaction_type='reversal'` + `reverses_tx_id`.
- trigger `apply_reversal` (BEFORE INSERT): original را می‌خواند و **خودش** پر می‌کند:
  `portfolio_id/account_id/participant_id/asset_id` را از original، و
  `quantity_delta = -orig.quantity_delta`, `cash_delta_rial = -orig.cash_delta_rial`, `cost_basis_rial = -COALESCE(orig.cost_basis_rial, 0)`.
- ممنوع: self-reverse، reverse یک reversal، portfolio mismatch، reverse ناموجود، reverse دوباره (partial unique).
- **Reconstruction:** دو راه معادل —
  (الف) naive `SUM` روی همه‌ی transactions (چون reversal دقیقاً معکوس است)، یا
  (ب) روی view `portfolio.effective_transactions` که originalهای reversed و reversalها را حذف می‌کند.
  هر دو برای cash/quantity/avg-cost نتیجه‌ی یکسان می‌دهند؛ (ب) معنی cancellation را صریح می‌کند.
- **Average cost:** برای `opening_position`، `cost_basis_rial` ساختاریافته ورودی است؛ reversal آن را negate می‌کند، پس `SUM(COALESCE(cost_basis_rial,0))` برای pair صفر می‌شود.

## ۱۶) Account در ledger
`transactions.account_id NOT NULL` + composite FK به همان portfolio. برای migration legacy یک account synthetic (`account_type='cash'`) ساخته می‌شود.

## ۱۷) Asset/Security metadata
- `assets.name`/`symbol` برای assetهای security-linked nullable؛ `CHECK (security_id IS NOT NULL OR name IS NOT NULL)`.
- نمایش از view `portfolio.assets_resolved` (COALESCE با company/security) → بدون duplicate mutable metadata.

## ۱۸) Analytics immutability
trigger append-only برای `company_scores`, `factor_scores`, `metric_snapshots`. `score_runs` فقط lifecycle-mutable (trigger identity).
`score_version` فقط در `score_runs`.

## ۱۹) Uniqueness و PK (خلاصه‌ی نهایی)
- `daily_prices` = view (بدون PK).
- `price_observations` PK `bigint identity`، dedup `UNIQUE(observation_hash)`.
- normalized: `UNIQUE(parse_run_id)` / `UNIQUE(parse_run_id, statement_type)`.
- analytics: `UNIQUE(run_id, company_id)` / `(+factor_code)` / `(as_of,company,metric,calc_version)`.
- `companies.normalized_name` غیریکتا؛ `securities UNIQUE(id, company_id)`.

## Delete behavior (نهایی)
CASCADE فقط برای فرزندِ متعلقِ mutable (report_versions→? no: RESTRICT؛ participants/accounts/positions/valuation→portfolios CASCADE؛ company_scores→score_runs CASCADE؛ security_aliases→securities CASCADE).
RESTRICT برای chainهای audit/history (reports→versions، versions→payloads، statements→facts، price_observations→securities، transactions→portfolios، analytics→securities).
