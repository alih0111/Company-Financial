# REMAINING READ ENDPOINT AUDIT

Audited against actual Go handlers and the React client (`client/src`). The goal
is API/data integrity, not legacy v3.7 reproduction.

| Route | Handler | Legacy data | Contains | Classification |
| --- | --- | --- | --- | --- |
| `GET /api/AllCompanyScores` | `handlers.GetCompanyScores` | `mahane.Value3`, `miandore2.Product1/OperatingProfitNew/RevenueNew`, `FullPE` | in-Go legacy presentation scoring (Product1 heuristic) | **CANONICAL_READ_READY** |
| `GET /api/CompanyScores` | `handlers.GetCompanyScores2` | `mahane.Value3`, `miandore2.Product1`, `FullPE` | in-Go legacy per-company scoring | **CANONICAL_READ_READY** |
| `GET /api/StockPriceScore` | `handlers.StockPriceScore` | `dbo.StockData` (32,958 rows) | technical indicators (MA/RSI/MACD/volatility) | **OUT_OF_SCOPE_FOR_CURRENT_MODEL** |
| `GET /api/detail` | `handlers.GetAIStockDetail` | `vw_AIStockMetrics`, `mahane`, `miandore2`, `MarketPriceHistory` | legacy score + raw points | **CANONICAL_READ_ADAPTABLE** |
| `POST /api/analyze` | `handlers.AnalyzeTopStocksWithAI` | `vw_AIStockMetrics` + external LLM | legacy scores + AI text | **LEGACY_AI_ONLY** |

## Rationale

### CANONICAL_READ_READY — AllCompanyScores, CompanyScores
Both are quantitative score endpoints and now have canonical read paths backed by
`analytics.company_scores` + `analytics.factor_scores` (no Go scoring arithmetic):

- `integration.AllScoreInputRow` / `PG.AllScoresCanonical` (single indexed query
  with lateral latest-price lookup).
- `integration.CompanyScoreBundle` / `PG.CompanyScoreByLegacyID` (identity via
  `core.legacy_entity_map`, never names).
- SHADOW comparators: `Shadow.CompareAllCompanyScores`,
  `Shadow.CompareCompanyScores`.

Legacy fields reproduced for client compatibility where a canonical meaning
exists; legacy-only fields documented (see below). SHADOW result: **0 unexpected**
(AllCompanyScores 267 matched/276 legacy; CompanyScores 9 matched/12 sample).

### OUT_OF_SCOPE_FOR_CURRENT_MODEL — StockPriceScore
Pure technical analysis over `dbo.StockData`; not a fundamental/analytics score
and not backed by canonical analytics. The React client destructures
`stockPriceScore` but does **not** render it. It is not part of the current
quantitative model and must not be reimplemented as fundamental analytics.
Canonical technical indicators, if wanted later, belong in the market engine.

### CANONICAL_READ_ADAPTABLE — detail
Composes the summary score with monthly/profit/market point series. The route is
declared as `GET /api/detail` without a `:companyID` parameter, so it is
effectively unreachable as written. It is adaptable to canonical once a company
identifier is put in the path; not blocking and not migrated now.

### LEGACY_AI_ONLY — analyze
LLM qualitative analysis layered on legacy v3.7 rows. Per the project rules,
LLM/AI may assist explanation but deterministic code controls scoring. Migrating
this means feeding canonical score rows to the AI prompt, which is a later phase
and depends on the canonical summary migration. Not in scope here.

## Legacy → canonical field mapping (AllCompanyScores / CompanyScores)

| Legacy field | Canonical source | Class |
| --- | --- | --- |
| `company_id` | `core.legacy_entity_map.legacy_key` | compatibility key |
| `company_name` | `core.companies.display_name` | IDENTITY_PRESENTATION_DIFFERENCE |
| `sales_growth` | factor `SalesGrowth.raw_value` | EXPECTED_CANONICAL_SEMANTIC_CHANGE |
| `eps_growth` | factor `NetProfitGrowth.raw_value` (substitute, not EPS-specific) | EXPECTED_CANONICAL_SEMANTIC_CHANGE |
| `pe` | factor `PE.raw_value` | EXPECTED_CANONICAL_SEMANTIC_CHANGE |
| `price` | latest `market.price_observations.closing_price_rial` | EXPECTED_CANONICAL_SEMANTIC_CHANGE |
| `operation` | factor `OperatingMargin.raw_value` | EXPECTED_CANONICAL_SEMANTIC_CHANGE |
| `finalScore` | `analytics.company_scores.quant_score` | EXPECTED_CANONICAL_SEMANTIC_CHANGE |
| `Stable` | — | **LEGACY_ONLY_FIELD** (no canonical equivalent; never fabricated) |
| category/quant/dq scores | `analytics.company_scores` | CANONICAL_ONLY (additive) |

Machine-readable: `output/remaining_endpoint_audit.csv`.
