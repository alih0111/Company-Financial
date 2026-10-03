# SYMBOL PAGE UI CONTRACT

Defines the exact API fields and ordering each symbol-page component consumes,
and the canonical presentation rules. Verified against the live React app.

## Panel → endpoint map

| UI panel | Component | Endpoint | Fields consumed | Ordering required |
| --- | --- | --- | --- | --- |
| Upper profit/EPS chart | `ChartComponent` (data1) | `GET /api/SalesData` | `reportDate`, `percentage`, `wow` | oldest → newest (left→right) |
| EPS-growth donut | `DonutChartComponent` | `GET /api/summary` | `net_profit_growth_4_reports` (raw %, label «رشد سود خالص») | – |
| Lower sales chart | `ChartComponent` (data2) | `GET /api/SalesData2` | `reportDate`, `percentage`, `wow` | oldest → newest |
| Sales-growth donut | `DonutChartComponent` | `GET /api/summary` | `sales_growth_12m` (raw %, label «رشد فروش») | – |
| Price chart | `PriceChart` | `GET /api/price-history` | `date`,`jalali_date`,`closing_price`,… | newest→oldest (component handles) |
| Company selector | `CompanySelect` | `GET /api/CompanyNames` | `string[]` | alphabetical |
| Top KPI cards | `App.tsx` | `GET /api/summary` (`getAIStockSummary`) | `quant_score`, `sales_growth_12m`, `pe_approx`, category scores | – |
| Score breakdown | `ScoreBreakdown` | `GET /api/summary` (same rows, keyed by `company_id`) | category scores, penalties, `*_rank` (0–1), base metric values | – |
| Score table | `BigDataTable` | `/api/AllCompanyScores` merged with `/api/summary` | `company_id`,`company_name`,`eps_growth`,`sales_growth`,`pe`,`stable`,`operation`,`quant_score` | – |

Key: `App.tsx` builds `aiRows` from `/api/summary` and looks up `currentMetric = aiRows[company_id]`; `ScoreBreakdown` and the KPI cards read that row.

## Presentation contract

### `GET /api/SalesData` (upper chart)
- Bar height `percentage` = canonical **EPS** (`rial_per_share`, rounded 2dp).
  Rationale: canonical `net_profit` is materialized only for the latest report
  for most companies; EPS is complete across ~29 periods, so the chart shows the
  full history. This replaces the deprecated mixed-scale `Product1 = EPS×Capital`.
- `wow` = sign relation of current vs previous (chronological) EPS.
- Ordering: **oldest → newest** (backend guarantees).
- `Product1/2/3` are **deprecated compatibility fields**, emitted as `0`, never
  derived, not a canonical fact.

### `GET /api/SalesData2` (lower chart)
- `percentage = round(sales_amount_rial / 1e9, 2)`; `wow` from signs of
  production/sales/amount (see `integration.MonthlyPresentation`).
- Ordering: **oldest → newest** (backend guarantees).
- Empty history → `200 []` (explicit), not an error.

### Donuts (upper = net-profit growth, lower = sales growth)
- Donut value = **raw factor growth %** from `GET /api/summary`
  (`net_profit_growth_4_reports`, `sales_growth_12m`) — the same source as the
  KPI cards, so the gauge reads «رشد سود خالص ۳۲۷.۳٪» / «رشد فروش ۷۴.۸٪».
- Ring fill clamps to 0–100 (growth >100 → full ring, negative → empty ring);
  the center label prints the unclamped raw value.
- Donut renders only when the summary row exists and the value is non-null.
- Factor **percentile ranks** (former donut source, `CompanyScores`
  `epsGrowth`/`salesGrowth` = percentile × 100) remain visible in the score
  breakdown section, not on the donuts.

### `GET /api/CompanyScores`
- `epsGrowth`, `salesGrowth`, `operation`, `salesStability`, `epsLevel` = canonical
  factor **percentile × 100** (0–100). Canonical-v1 does not materialize factor
  raw values, so a rank-based score is the honest presentation.
- `finalScore`/`quantScore` = canonical `quant_score`; category scores included.
- No canonical score for the company → `200 []`.

### `GET /api/summary` (KPI + score breakdown)
- `quant_score`, `growth_score`, `profitability_score`, `valuation_score`,
  `market_score`, `data_quality_score`, `score_version` from `analytics.company_scores`.
- `*_rank` fields = canonical `analytics.factor_scores.percentile` (0–1) → drive
  the score-detail progress fills.
- Base metric **value** fields are emitted as JSON `null` when canonical-v1 does
  not materialize the raw value. The UI renders `--` (explicit missing), **not** a
  misleading `0`.
- Penalty fields = 0 (canonical applies penalties inside the category score).

## Score-display contract

Category `maxScore` is fixed by the UI (growth 36, profitability 26, valuation 16,
market 11); category fill = `actual_score / max_score`. Factor fill =
`rank` (0–1). Earned/max = `weight × rank` / `weight`. Missing/unavailable factor
→ `rank = 0` and value `null` (UI shows "بدون داده → 30%" behaviour via
`neutralWhenNull` where applicable).

## Null/zero semantics
- Canonical missing value → `null` in JSON → UI shows `--`.
- True zero → `0` and is displayed as `0` (e.g., EPS 0 in an early period).
- No silent missing→0 conversion for score-chart bars.
