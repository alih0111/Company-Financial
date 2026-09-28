# SYMBOL PAGE BUGFIX REPORT

**Gate: `SYMBOL_PAGE_UI_FIXED`**

Debugged the real symbol page end-to-end: React → API → Go handlers → canonical
repositories → response JSON → chart/progress rendering. SQL Server stopped.

## Broken UI components and root causes

### 1. Upper profit/EPS chart — collapsed to one bar
- **Endpoint:** `GET /api/SalesData`.
- **Root cause:** the canonical serving derived the bar height from canonical
  **net_profit**, which the migration materialized only for the **latest** report
  for most companies (`net_profit` periods ≈ 1 of ~29; `eps` ≈ 29 of 29). So
  `percentage` was nonzero on 1/28 rows → one visible bar. Also the canonical
  rows were returned **newest-first**, the reverse of the legacy ascending order.
- **Fix:** derive `percentage` from canonical **EPS** (`rial_per_share`), return
  **oldest→newest**. `integration.EpsPercentage`, `integration.OrderFinancialAscending`.
- **Result:** کسرا 27/28 nonzero in ASC order (was 1/28); چکاپا 27/30.

### 2. Lower sales chart — wrong order
- **Endpoint:** `GET /api/SalesData2`.
- **Root cause:** canonical rows returned **newest-first**; the chart renders in
  array order (expects oldest→newest).
- **Fix:** `integration.OrderMonthlyAscending` in `monthlyCanonicalResponse`.
- **Result:** کسرا/چکاپا/دزهراوی now 1399→1405 ascending.

### 3. Score-detail fill/progress — empty bars
- **Endpoint:** `GET /api/summary` (rows keyed by `company_id`).
- **Root cause:** the canonical summary served only category/quant scores; all
  `*_rank` fields (which the UI uses for progress-bar width and earned/max) were
  `0`, and base values were `0` (misleading) instead of missing.
- **Fix:** `integration.AllScoreInputRow` now carries `FactorRanks` from
  `analytics.factor_scores.percentile`; a dedicated canonical response
  (`handlers/summary_canonical.go`) maps them to the UI rank fields and emits
  unavailable base values as JSON `null`.
- **Result:** ranks populate (e.g., غاذر `sales_growth_rank=0.958`,
  `pe_rank=0.391`, `roe_rank=0.694`); base values `null` → UI `--`.

### 4. Top KPI contract — missing treated as zero
- **Root cause:** canonical summary emitted `0` for unavailable base metrics, so
  the KPI cards showed `0.0%` instead of a missing state.
- **Fix:** pointer/null semantics (above). KPIs now show `--` when unavailable.

### 5. Transient 503s in offline mode
- **Endpoint:** price-history / SalesData2 / SalesData.
- **Root cause:** canonical fetches used the short canary timeout (1.5–2 s); under
  first-load load, a slow query returned `503 sqlserver_offline_expected`.
- **Fix:** offline mode uses a 15 s canonical timeout
  (`integration.offlineCanonicalTimeout`); and legitimately-empty data returns
  `200 []` instead of `503`.

## Legacy vs canonical contract differences

| Field | Legacy | Canonical (fixed) | Classification |
| --- | --- | --- | --- |
| SalesData rows | Product1!=0 filter, ASC | full EPS history, ASC | BACKEND_BUG (was collapsed/reversed) |
| SalesData `percentage` | Product1/1e6 (heuristic) | EPS (2dp) | LEGACY_HEURISTIC_FIELD replaced by explicit canonical presentation |
| SalesData `Product1/2/3` | required | emitted 0, unused | LEGACY_HEURISTIC_FIELD (deprecated) |
| SalesData2 order | ascending | ASC (fixed) | ORDERING_DIFFERENCE (fixed) |
| summary `*_rank` | v3.7 percentiles | canonical factor percentiles | EXACT semantics (now populated) |
| summary base values | numeric | `null` when unmaterialized | NULL_SEMANTICS_DIFFERENCE (explicit) |
| CompanyScores `epsGrowth` | growth % | factor percentile×100 | EXPECTED_CANONICAL_SEMANTIC_CHANGE |

## Code changes
- `integration/presentation.go`: `OrderFinancialAscending`, `OrderMonthlyAscending`,
  `EpsPercentage`, `FactorRank`, `FactorRaw`.
- `integration/scores.go`: `AllScoreInputRow.FactorRanks/FactorRaw` populated from
  `analytics.factor_scores`.
- `integration/canary.go`, `fundamentals_canary.go`: 15 s offline canonical timeout.
- `handlers/sales_data.go`: EPS-based, ASC SalesData presentation.
- `handlers/sales_data2.go`: ASC monthly response.
- `handlers/company_score.go`: rank-based donut values.
- `handlers/summary_canonical.go`: canonical summary response (ranks + null base).
- `handlers/{sales_data,sales_data2,company_score}.go`: empty canonical → `200 []`.

## Real browser verification (Playwright, live site)
Frontend `localhost:3000` (proxy `rfa.systemgroup.net`), SQL Server stopped,
authenticated session, symbols کسرا، چکاپا، دزهراوی، کیمیا، شکیمیا (incl. unsafe):

**All `/api/*` responses 200; zero 5xx; zero SQL attempts.**

## Remaining limitations
- Canonical-v1 does not materialize factor raw values, so base metric **text**
  (e.g., growth %, P/E) shows `--`; ranks/fills and category scores are correct.
  Resolving this requires persisting `raw_value` in `analytics.factor_scores`
  (future analytics change; not scoring-formula change).
- Chart bar metric for the upper panel is EPS (documented presentation choice).
