# `dbo.miandore2` → Fundamentals Fact Mapping (column by column)

> Design artifact. هیچ داده‌ای مهاجرت نکرده است.
> قواعد:
> - statementهای سه‌گانه: `income_statement`، `balance_sheet`، `cash_flow`.
> - `period_order`: 1 = current، 2 = prior year same period، 3 = prior fiscal year.
> - `comparison_type`: `current` | `prior_year_same_period` | `prior_fiscal_year`.
> - مبالغ legacy = **million_rial** → `reported_value` (بدون تغییر) + `canonical_value = ×1,000,000` (ریال).
> - EPS legacy = **rial_per_share** → `reported_value = canonical_value` (بدون تبدیل).
> - `Product1/2/3` → **LEGACY_DERIVED_DO_NOT_MIGRATE_AS_FACT** (مقیاس مخلوط).

## هدر گزارش
| legacy | new |
| --- | --- |
| `CompanyID` | resolve → `financial_statements.company_id` (+ legacy map) |
| `CompanyName` | `core.companies.display_name` candidate / alias |
| `ReportDate` | `financial_statements.period_end_date` (Greg) + `jalali_*`/fiscal |
| `Url` | `ingestion.reports.source_url` |
| `ID` | ignore |

## `income_statement` (period_order از پسوند، comparison از نوع)

| legacy column | metric_code | period_order | comparison_type | reported_unit | canonical_unit | تبدیل |
| --- | --- | --- | --- | --- | --- | --- |
| `Num1_Value1` | `eps` | 1 | current | rial_per_share | rial_per_share | — |
| `Num4_Value1` | `operating_eps` | 1 | current | rial_per_share | rial_per_share | — |
| `Num2_Value1` | `capital` | 1 | current | million_rial | rial | ×1e6 |
| `OperatingProfitNew` | `operating_profit` | 1 | current | million_rial | rial | ×1e6 |
| `FinanceCostsNew` | `finance_cost` | 1 | current | million_rial | rial | ×1e6 |
| `OtherNonOpNew` | `other_non_operating` | 1 | current | million_rial | rial | ×1e6 |
| `RevenueNew` | `revenue` | 1 | current | million_rial | rial | ×1e6 |
| `NetProfitAmount` | `net_profit` | 1 | current | million_rial | rial | ×1e6 |
| `Num1_Value2` | `eps` | 2 | prior_year_same_period | rial_per_share | rial_per_share | — |
| `Num4_Value2` | `operating_eps` | 2 | prior_year_same_period | rial_per_share | rial_per_share | — |
| `Num2_Value2` | `capital` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `OperatingProfitLastYear` | `operating_profit` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `FinanceCostsLastYear` | `finance_cost` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `OtherNonOpLastYear` | `other_non_operating` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `RevenueLastYear` | `revenue` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `NetProfitAmountLY` | `net_profit` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `Num1_Value3` | `eps` | 3 | prior_fiscal_year | rial_per_share | rial_per_share | — |
| `Num4_Value3` | `operating_eps` | 3 | prior_fiscal_year | rial_per_share | rial_per_share | — |
| `Num2_Value3` | `capital` | 3 | prior_fiscal_year | million_rial | rial | ×1e6 |
| `OperatingProfitFYPrev` | `operating_profit` | 3 | prior_fiscal_year | million_rial | rial | ×1e6 |
| `RevenueFYPrev` | `revenue` | 3 | prior_fiscal_year | million_rial | rial | ×1e6 |
| `NetProfitAmountFYPrev` | `net_profit` | 3 | prior_fiscal_year | million_rial | rial | ×1e6 |

> `Num2_Value3` بر اساس parser کم‌استفاده است و معنای FYPrev آن قطعی نیست؛ در صورت NULL بودن، رکورد ساخته نمی‌شود.

## `balance_sheet` (current = دوره‌ی جاری، LY = پایان سال قبل)

| legacy column | metric_code | period_order | comparison_type | reported_unit | canonical | تبدیل |
| --- | --- | --- | --- | --- | --- | --- |
| `TotalAssets` | `total_assets` | 1 | current | million_rial | rial | ×1e6 |
| `TotalAssetsLY` | `total_assets` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `CurrentAssets` | `current_assets` | 1 | current | million_rial | rial | ×1e6 |
| `CurrentAssetsLY` | `current_assets` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `TotalLiabilities` | `total_liabilities` | 1 | current | million_rial | rial | ×1e6 |
| `TotalLiabilitiesLY` | `total_liabilities` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `CurrentLiabilities` | `current_liabilities` | 1 | current | million_rial | rial | ×1e6 |
| `CurrentLiabilitiesLY` | `current_liabilities` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `TotalEquity` | `total_equity` | 1 | current | million_rial | rial | ×1e6 |
| `TotalEquityLY` | `total_equity` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |

> `is_cumulative` برای balance sheet = `false` (موجودی نقطه‌ای).

## `cash_flow`

| legacy column | metric_code | period_order | comparison_type | reported_unit | canonical | تبدیل |
| --- | --- | --- | --- | --- | --- | --- |
| `OperatingCashFlow` | `operating_cash_flow` | 1 | current | million_rial | rial | ×1e6 |
| `OperatingCashFlowLY` | `operating_cash_flow` | 2 | prior_year_same_period | million_rial | rial | ×1e6 |
| `OperatingCashFlowFYPrev` | `operating_cash_flow` | 3 | prior_fiscal_year | million_rial | rial | ×1e6 |

> `is_cumulative = true` (جریان نقدی تجمعی از ابتدای سال؛ طبق parser).

## ستون‌های legacy که مهاجرت نمی‌شوند

| legacy column | تصمیم | دلیل |
| --- | --- | --- |
| `Product1` | **LEGACY_DERIVED_DO_NOT_MIGRATE_AS_FACT** | `EPS × Capital`، مقیاس مخلوط؛ صرفاً در RAW/audit |
| `Product2` | **LEGACY_DERIVED_DO_NOT_MIGRATE_AS_FACT** | همان |
| `Product3` | **LEGACY_DERIVED_DO_NOT_MIGRATE_AS_FACT** | همان |

## Metric Dictionary entries (نمونه‌های لازم)
| metric_code | statement_type | canonical_name | display_name_fa | expected_unit |
| --- | --- | --- | --- | --- |
| `eps` | income_statement | Earnings per share | سود خالص هر سهم | rial_per_share |
| `operating_eps` | income_statement | Operating EPS | سود عملیاتی هر سهم | rial_per_share |
| `capital` | income_statement | Registered capital | سرمایه | rial |
| `operating_profit` | income_statement | Operating profit | سود عملیاتی | rial |
| `finance_cost` | income_statement | Finance cost | هزینه مالی | rial |
| `other_non_operating` | income_statement | Other non-operating | سایر درآمد/هزینه غیرعملیاتی | rial |
| `revenue` | income_statement | Revenue | درآمد عملیاتی | rial |
| `net_profit` | income_statement | Net profit | سود خالص | rial |
| `total_assets` | balance_sheet | Total assets | جمع دارایی‌ها | rial |
| `current_assets` | balance_sheet | Current assets | دارایی جاری | rial |
| `total_liabilities` | balance_sheet | Total liabilities | جمع بدهی‌ها | rial |
| `current_liabilities` | balance_sheet | Current liabilities | بدهی جاری | rial |
| `total_equity` | balance_sheet | Total equity | حقوق مالکانه | rial |
| `operating_cash_flow` | cash_flow | Operating cash flow | جریان نقدی عملیاتی | rial |
