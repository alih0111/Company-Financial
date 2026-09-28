# FINAL READ CANARY REPORT

**Gate: `FINAL_CANONICAL_READ_CANARY_PASS`**

Bounded, read-only canary of the endpoints judged ready. Drives the real Gin
handlers (`httptest`) against live shadow PostgreSQL + legacy SQL Server, with the
identity eligibility guard, automatic legacy fallback and failure injection.
No production cutover; SQL Server retained.

- Harness: `go-app/cmd/finalcanary`
- Artifacts: `output/final_read_canary.csv`, `output/final_read_canary_summary.json`
- Injection artifacts: `output/canary_inject_pg/`, `output/canary_inject_run/`
- Read mode: `LEGACY` (canonical serving only via the fund/price canary allowlist)

## Representative cohort (deterministic)

Safe: `وسپه`, `خودرو`, `بفجر`, `دزهراوی`, `کیمیا`, `غاذر`, `کسرا`, `چکاپا`,
`افق`, `هجرت` (strong/sparse fundamentals, different fiscal years, report-chain
TTM, missing-factor, long market history).

Unsafe controls: `جم پیلن`, `های وب` (legacy identity collision), `خاهن`,
`شخارک`, `شکیمیا` (legacy-only).

## Results (normal run)

| Endpoint | requests | canonical | legacy | fallbacks | HTTP errors | exact | expected | unexpected | p50 ms | p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SalesData2 | 15 | 8 | 5 | 2 | 0 | 2260 | 573 | **0** | 12.9 | 13.0 |
| AllCompanyScores | 1 | 1 | 0 | 0 | 0 | 523 | 1089 | **0** | 124.9 | 136.1 |
| CompanyScores | 15 | 10 | 5 | 0 | 0 | 19 | 26 | **0** | 39.0 | 39.4 |
| price-history | 15 | 10 | 5 | 0 | 0 | 1960 | 0 | **0** | 97.5 | 103.2 |

- **0 unexplained mismatches**, **0 HTTP errors**, **0 writes** by read paths.
- `EXPECTED_UNIT_PRESENTATION` (SalesData2) and
  `EXPECTED_CANONICAL_SEMANTIC_CHANGE` (score endpoints) are the documented
  classifications, not defects.
- SalesData2 fallbacks (2): safe identity whose canonical monthly set is empty
  (market-only company) → automatic legacy fallback with HTTP 200.

## Identity guard

| Name | Classification | Eligible |
| --- | --- | --- |
| وسپه, خودرو, بفجر, دزهراوی, کیمیا, غاذر, کسرا, چکاپا, افق, هجرت | CANONICAL_SAFE | true |
| جم پیلن, های وب | LEGACY_IDENTITY_COLLISION | false |
| خاهن, شخارک, شکیمیا | LEGACY_ONLY | false |

Unsafe/ambiguous identities were **forced to legacy**; none became canonical
eligible. Guard runs before selection and default-denies.

## Analytics freshness (never stale-as-fresh)

- `score_version = canonical-v1-dev`
- `score_run_id = 489a6df0-2d37-44de-a0c5-ef0d5daa7191`, `score_as_of = 2026-09-25`
- `data_as_of = 2026-09-22`, `score_stale = false`
- CompanyScores canonical responses carry `scoreVersion/scoreAsOf/dataAsOf/scoreStale`.
- A missing/stale run is never served as a current score (see injection).

## Failure injection

| Injection | Result |
| --- | --- |
| PostgreSQL unavailable (`CDF_CANONICAL_DB` nonexistent) | canonical_configured=false; all 31 canonical attempts fell back to legacy; HTTP 200; 0 unexpected |
| Missing completed score run (`canonical-v9-nonexistent`) | AllCompanyScores 0 canonical / 1 fallback; CompanyScores 0 canonical / 10 fallback; HTTP 200; no score presented as current |
| Unsafe identity | routed legacy directly (guard) |

## Contract validation

Every response was structurally validated: SalesData2 keys
(`companyName,companyID,reportDate,value1,value2,value3,percentage,wow`),
AllCompanyScores keys (`company_id,company_name,sales_growth,eps_growth,pe,price,Stable,operation`),
CompanyScores keys (`companyID,companyName,salesGrowth,epsGrowth,finalScore`),
price-history keys. No missing keys, no type/contract breakage.

## Presentation

SalesData2 uses `integration.MonthlyPresentation`
(`percentage = round(sales_amount_rial/1e9, 2)`, `wow` sign derivation).
`Product1/2/3` are not involved.

## Not canaried (unchanged)

`SalesData`, `CompanyNames`, `StockPriceScore`, `detail`, `analyze` remain
legacy/shadow.

## Outcome

`FINAL_CANONICAL_READ_CANARY_PASS` — proceed to Model v2 (Part B).
