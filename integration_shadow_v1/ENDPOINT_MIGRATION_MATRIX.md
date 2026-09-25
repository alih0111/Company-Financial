# ENDPOINT MIGRATION MATRIX — Phase 1 + Phase 2

Selected shadow endpoints are read-only, high-value, and have well-defined
canonical semantics. Legacy response shape is unchanged.

## Selected for SHADOW (Phase 1)

### 1. `GET /api/CompanyNames` — company/security identity

| Field | Value |
| --- | --- |
| Handler | `handlers.GetCompanyNames` (`go-app/handlers/sales_data.go`) |
| Current source | SQL Server `miandore2` — `SELECT DISTINCT CompanyName FROM miandore2 ORDER BY CompanyName` |
| Canonical source | `core.companies` — `COALESCE(NULLIF(BTRIM(display_name),''), BTRIM(legal_name))` |
| Comparison key | normalized `CompanyName` (Persian digit/ی/ک normalization, whitespace collapsed) |
| Expected semantic differences | canonical population (273) vs legacy (267); identity is Company UUID, names are aliases; `CANONICAL_ONLY` / `LEGACY_ONLY` allowed |
| Shadow-ready | yes |
| Cutover-ready | no (name is not a canonical identity key; a translation layer is required) |
| Comparison result | 263 matched / 267 legacy / 273 canonical; expected 14 (10 canonical-only, 4 legacy-only); 0 unexpected |

### 2. `GET /api/price-history` — market daily data

| Field | Value |
| --- | --- |
| Handler | `handlers.GetPriceHistory` (`go-app/handlers/price_history.go`) |
| Current source | SQL Server `MarketPriceHistory` (`CompanyName`/`Symbol`, order `GregorianDate DESC`) |
| Canonical source | `market.daily_prices` joined to security resolved via `core.security_aliases` / `core.securities.codal_symbol|brs_name` |
| Comparison key | `trade_date` (normalized `YYYY-MM-DD`) |
| Compared fields | `closing_price`, `last_price`, `high_price`, `low_price`, `volume`, `trade_value`, `change_percent` |
| Expected semantic differences | canonical is the adjusted series; legacy may be unadjusted; unit difference (IRR vs million-IRR) classified as `EXPECTED_UNIT_PRESENTATION`; row pop differences allowed |
| Shadow-ready | yes |
| Cutover-ready | **canary-ready** (see below); full cutover still gated on broad rollout evidence |
| Comparison result | 180 legacy / 180 canonical / 180 matched; 0 expected, **0 unexpected** across 6 symbols |
| Canary reason | canonical serves the exact legacy JSON contract with deterministic selection, automatic legacy fallback, config-only kill switch and 0 unexpected diffs |

**Canary (Phase 3):** `GET /api/price-history` is the only endpoint with an
endpoint-level canonical read canary. Controlled by
`CDF_PRICE_HISTORY_CANARY_ENABLED` + `CDF_PRICE_HISTORY_CANARY_SYMBOLS`
(deterministic allowlist, optional hashed percentage), canonical timeout and
fallback. See `PRICE_HISTORY_CANARY_SPEC.md`, `PRICE_HISTORY_CANARY_RUNBOOK.md`
and `PRICE_HISTORY_CANARY_REPORT.md`.

**Production canary Batch 1 (Phase 4):** bounded 3-symbol canary
(`کیمیا`, `غاذر`, `کسرا`), 45 canonical-served / 0 fallback / 0 unexpected /
0 errors, canonical median 2.11 ms; kill switch exercised. Gate:
`PRICE_HISTORY_PRODUCTION_CANARY_PASS`.

**Production canary Batch 2 (Phase 5):** bounded 5-symbol batch
(`وسپه`, `خودرو`, `بفجر`, `مبین`, `دزهراوی`; control `سباقر`), 90
canonical-served / 0 organic fallback / 0 unexpected over 95 requests,
canonical median 1.57 ms; controlled timeout fallback exercised (5/5);
kill switch re-exercised. Two alias/revision symbols (`جم پیلن`, `های وب`) were
evaluated and **excluded** due to a legacy duplicate-symbol identity collision.
Gates: `PRICE_HISTORY_CANARY_BATCH2_PASS`,
`PRICE_HISTORY_PERCENT_ROLLOUT_NOT_READY`.

**Identity eligibility guard (Phase 6):** canonical serving requires
`CANONICAL_SAFE` in the audited identity-eligibility registry (285 symbols → 276
safe, 3 collisions: جم پیلن/سیمرغ/های وب, 5 legacy-only, 1 unmapped). The guard
runs before allowlist/percentage selection; unsafe symbols are forced to legacy
and can never be canonical-served. Default-deny on a missing registry. Gate:
`PRICE_HISTORY_IDENTITY_GUARD_READY`. Registry:
`output/price_history_identity_eligibility.csv`; simulation:
`output/price_history_percent_simulation.json`; details:
`PRICE_HISTORY_IDENTITY_ELIGIBILITY.md`.

**5% percentage rollout (Phase 7):** deterministic 5% of `CANONICAL_SAFE` (14
symbols, 0 unsafe) via `CDF_PRICE_HISTORY_CANARY_PERCENT=5`, `VERIFY=true`,
identity guard active, no allowlist. 115 real requests / 115 × 200, 70
canonical-served, 0 fallback, **expected 0 / unexpected 0**, canonical median
1.68 ms. A date-coverage gap (`های وب3` and 3 others) was found and fixed by a new
`LEGACY_COVERAGE_DIVERGENCE` classification before the clean run. Gate:
`PRICE_HISTORY_PERCENT5_PASS`; next-step assessment `PRICE_HISTORY_PERCENT10_READY`
(not executed). Every other endpoint remains disabled; global canonical mode not
enabled.

See `PRICE_HISTORY_PERCENT_ROLLOUT_REPORT.md`,
`PRICE_HISTORY_PRODUCTION_CANARY_REPORT.md` (Batch 1 + Batch 2 + guard +
5% sections).

### 3. `GET /api/summary` — canonical analytics / score results

| Field | Value |
| --- | --- |
| Handler | `handlers.GetAIStockSummary` (`go-app/handlers/ai_stock_handler.go`) |
| Current source | SQL Server view `dbo.vw_AIStockMetrics` (v3.7 QuantScore, top-N by `QuantScore DESC`) |
| Canonical source | `analytics.company_scores` joined to selected `analytics.score_runs` run (`score_version = canonical-v1-dev`) |
| Comparison key | legacy 32-hex `CompanyID` resolved via `core.legacy_entity_map` (`entity_type='company'`, `source_table IN ('miandore2','mahane')`) |
| Compared fields | `symbol`, `company_name` (identity), `quant_score`, `data_quality_score`, `growth_score`, `profitability_score`, `valuation_score`, `market_score` |
| Expected semantic differences | canonical-v1 engine ≠ legacy v3.7 heuristic engine; canonical population 267 vs view 276; all score deltas are `EXPECTED_CANONICAL_SEMANTIC_CHANGE` |
| Shadow-ready | yes |
| Cutover-ready | no (intentional semantic change; requires product decision) |
| Comparison result | 20 legacy / 20 canonical / 20 matched; expected 84; **0 unexpected**; see latency note |

## Selected for SHADOW (Phase 2) — fundamentals

### 4. `GET /api/SalesData2` — monthly activities

| Field | Value |
| --- | --- |
| Handler | `handlers.GetSalesData2` (`go-app/handlers/sales_data2.go`) |
| Input | optional `companyName` (exact `CompanyName` match); otherwise all |
| Current source | SQL Server `mahane` — `CompanyName, CompanyID, ReportDate, Value1, Value2, Value3` |
| Legacy semantics | `Value1` = monthly production quantity; `Value2` = monthly sales quantity; `Value3` = monthly sales/recognised revenue amount in **million_rial**; `ReportDate` = Jalali `YYYY/MM/DD`; legacy response divides all three by 1e6 and computes `Percentage`/`WoW` (presentation only, unchanged) |
| Canonical source | `fundamentals.monthly_activities` (`production_quantity`, `sales_quantity`, `reported_sales_amount`, `sales_amount_rial`, `jalali_period_text`) via `core.legacy_entity_map` |
| Comparison key | `companyID|ReportDate` |
| Compared fields | `report_date` (identity), `production_quantity`, `sales_quantity`, `reported_sales_amount` (exact million_rial), `sales_amount_rial` (canonical IRR → `EXPECTED_UNIT_PRESENTATION`) |
| Expected differences | canonical population 12,075 vs legacy `mahane` 12,122; excluded/unmapped companies (`LEGACY_ONLY`); unit presentation on `sales_amount_rial` |
| Shadow-ready | yes |
| Cutover-ready | conditionally (needs legacy API unit decision) |
| Comparison result | 384 matched; 384 unit + 44 legacy-only expected; **0 unexpected** |

### 5. `GET /api/SalesData` — income-statement metrics

| Field | Value |
| --- | --- |
| Handler | `handlers.GetSalesData` (`go-app/handlers/sales_data.go`) |
| Input | optional `companyName` (exact match, `ORDER BY reportdate`); otherwise all |
| Current source | SQL Server `miandore2` — `CompanyName, CompanyID, ReportDate, Product1, Product2, Product3` (+ mapped metric columns read only for shadow) |
| Legacy semantics | `Product1/2/3` are **derived mixed-scale legacy heuristics** (`Product1 = EPS_current × Capital`, `Product2 = EPS_prior_year × Capital`, `Product3 = EPS_prior_fiscal × Capital`); `ReportDate` Jalali |
| Canonical source | `fundamentals.financial_facts` (income_statement, `period_order = 1`) joined through `financial_statements` + `ingestion.reports` |
| Comparison key | `companyID|ReportDate` |
| Compared fields | `report_date` (identity), `eps`, `revenue`, `operating_profit`, `net_profit`, `capital` (reported million_rial / rial_per_share) |
| Explicitly **not** compared | `Product1/2/3`: no canonical metric exists and the formula is a banned legacy heuristic; it is **not** re-derived in Go |
| Expected differences | unmapped legacy companies (`LEGACY_ONLY`) |
| Shadow-ready | yes |
| Cutover-ready | conditionally (the public `Product1/2/3` fields must be redefined at the API boundary) |
| Comparison result | 252 matched; 58 legacy-only expected; **0 unexpected** |

### Market query optimization (affects endpoint 2)

The Phase-1 canonical `market.daily_prices` read was rewritten to resolve the
security once and read `market.price_observations` directly. Semantics
(`latest adjusted observation`, `collected_at DESC, id DESC`) are unchanged and
verified equivalent. Median canonical latency 655.6 ms → 1.8 ms. See
`MARKET_QUERY_PROFILE.md`.

## Deferred (not shadow-enabled yet)

| Route | Reason |
| --- | --- |
| `GET /api/AllCompanyScores` | in-Go legacy scoring with legacy heuristics |
| `GET /api/CompanyScores` | in-Go legacy scoring |
| `GET /api/StockPriceScore` | depends on unmigrated `StockData` |
| `POST /api/GetUrl`, `POST /api/GetUrl2` | report URL; future |
| `GET /api/export/scores` | analytics consumption; future |
| `GET /api/export/scores` | analytics consumption; Phase 2 |
| `GET /api/detail` | route lacks `:companyID`; effectively broken |
| `POST /api/analyze` | external AI call + analytics |
| `/api/portfolio/*` | write paths |
| `/api/family/*` | write paths |
| `/api/run-script*`, `/api/fetchAllData`, `/api/sync-codal`, `/api/brs/collect`, `/api/FetchFullPE` | ingestion writes |

## Comparison classification glossary

`EXACT_MATCH`, `EXPECTED_UNIT_PRESENTATION`, `EXPECTED_CANONICAL_SEMANTIC_CHANGE`,
`LEGACY_ONLY`, `CANONICAL_ONLY`, `NULL_SEMANTICS_DIFFERENCE`,
`ORDER_ONLY_DIFFERENCE`, `NUMERIC_MISMATCH`, `IDENTITY_MISMATCH`, `QUERY_ERROR`,
`UNCLASSIFIED_MISMATCH`.

Numeric tolerance: exact for prices/volumes (`1e-6` relative) and
`1e-3` for `change_percent`. Tolerance is never used to hide a semantic mismatch;
score fields are explicitly classified as expected semantic change instead.
