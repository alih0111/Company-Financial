# v3.7 Population Reconciliation (282 → 276 → 273)

Read-only diagnostics (SQL Server SELECT + canonical shadow) performed during the
Exact v3.7 Compatibility Debugging task. No production DB/code and no canonical
facts were modified.

## Source of the v3.7 population (production view)

`dbo.vw_AIStockMetrics` is **not** filtered by `TrackedTickers`. Its row set is the
`CompanyList` CTE:

```sql
WITH CompanyList AS (
    SELECT CompanyID, MAX(CompanyName) AS CompanyName
    FROM ( SELECT CompanyID, CompanyName FROM dbo.mahane    WHERE CompanyID IS NOT NULL
           UNION ALL
           SELECT CompanyID, CompanyName FROM dbo.miandore2 WHERE CompanyID IS NOT NULL ) x
    GROUP BY CompanyID
)
```

So v3.7 population = **distinct `CompanyID` present in `mahane` OR `miandore2`**.

## Numbers (verified)

| object | value |
| --- | --- |
| `dbo.TrackedTickers` | **282** |
| distinct `CompanyID` in `mahane` | 193 |
| distinct `CompanyID` in `miandore2` | 267 |
| `CompanyList` union (v3.7 population) | **276** |
| `vw_AIStockMetrics` rows / distinct CompanyID | 276 / 276 |
| canonical `core.companies` / `core.securities` | **273** / 273 |
| canonical legacy map company rows | 822 |
| distinct legacy CompanyIDs mapped to canonical | 274 |
| canonical symbols found in v3.7 reference | 271 |
| v3.7 symbols **not** in canonical | **5** |
| canonical symbols **not** in v3.7 | **2** |

## Why 276 ≠ 273

The canonical shadow universe was built from **`TrackedTickers` ∩ `MarketPriceHistory`**
(`build_universe_manifest.py` requires price rows), whereas v3.7 uses
**`mahane` ∪ `miandore2`** regardless of tracked status or price availability.

### 5 v3.7 companies absent from canonical (no MarketPriceHistory → no price)

| legacy CompanyID | symbol | present in |
| --- | --- | --- |
| `09029850a7825c34a7c8958a08fcdf26` | خبهن | mahane |
| `326f53e9133b7e24c3b9ffec1e73fa18` | خاهن | miandore2 |
| `6081d3f368b7889ba242435db91b5b2f` | شکیمیا | miandore2 |
| `857898d4f504279f0355b95477392169` | ولشرق | mahane |
| `9ec90a47014c21843c4239f7a99a76f1` | شخارک | mahane + miandore2 |

All 5 have **zero** `MarketPriceHistory` rows, so they were excluded from the
canonical universe even though they carry fundamentals/monthly sales. They are
**real** companies (not fabrications); v3.7 scores them with neutral market ranks.

### 2 canonical companies absent from v3.7

| symbol | canonical name | reason |
| --- | --- | --- |
| مثقال | صندوق س.کالای آگاه | in `TrackedTickers` + `MarketPriceHistory` only |
| یاقوت | صندوق س یاقوت آگاه-ثابت | in `TrackedTickers` + `MarketPriceHistory` only |

These have no `mahane`/`miandore2` rows, so they never enter `CompanyList`.

### کسرا multi-ID convergence

`کاتالیست‌های صنعتی آریا` (symbol کسرا) has **2** legacy CompanyIDs
(`4ccc9664a47539eaff4b6b34fbfc0931`, `7e41b7…) converging to one canonical company,
hence 6 legacy-map company rows (2 cids × 3 source tables) and 274 distinct legacy
keys for 273 canonical companies. Only one of its two cids appears in v3.7.

## Consequence for rank/percentile parity

v3.7 ranks are computed over **276** subjects. The canonical compat layer only has
273 companies (271 with a v3.7 counterpart). Exact rank parity therefore requires
the compat population to be the **276 v3.7 subjects**; the 5 missing companies must
be present as canonical companies (real data, no fabrication) and the 2 funds must
be excluded from the rank denominator.

Until population is aligned, every rank/percentile factor and QuantScore is
structurally unable to match, independent of arithmetic correctness.

## Exact eligibility rule to reproduce

```
v3.7_eligible = has >=1 row in mahane OR has >=1 row in miandore2
```

`TrackedTickers` and price availability are **not** part of v3.7 eligibility.
