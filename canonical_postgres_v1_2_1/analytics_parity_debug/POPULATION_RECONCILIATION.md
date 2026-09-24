# v3.7 Population Reconciliation — COMPATIBILITY_ONLY_NOT_CANONICAL

Read-only SQL Server diagnostics + isolated shadow-only compatibility model.
No canonical company/security/fact was created or modified.

## Source of truth for the v3.7 scoring population

`dbo.vw_AIStockMetrics` has **no** `TrackedTickers` / price filter. Its row set is
the `CompanyList` CTE:

```sql
WITH CompanyList AS (
    SELECT CompanyID, MAX(CompanyName) AS CompanyName
    FROM ( SELECT CompanyID, CompanyName FROM dbo.mahane    WHERE CompanyID IS NOT NULL
           UNION ALL
           SELECT CompanyID, CompanyName FROM dbo.miandore2 WHERE CompanyID IS NOT NULL ) x
    GROUP BY CompanyID
)
```

⇒ exact v3.7 scoring population = `distinct CompanyID` in `mahane UNION miandore2`.

## Verified numbers

| object | value |
| --- | --- |
| `dbo.TrackedTickers` | 282 |
| distinct `mahane` CompanyID | 193 |
| distinct `miandore2` CompanyID | 267 |
| **`mahane UNION miandore2` (v3.7 subjects)** | **276** |
| `vw_AIStockMetrics` rows / distinct CompanyID | 276 / 276 |
| canonical `core.companies` / `core.securities` | 273 / 273 |
| **v3.7 subjects mapped to a canonical company** | **271** |
| **v3.7 subjects with no canonical company** | **5** |
| canonical companies not in v3.7 population | 2 (funds مثقال، یاقوت) |

## The 5 v3.7 subjects without a canonical mapping

These carry `mahane`/`miandore2` data but **zero** `MarketPriceHistory` rows, so the
canonical migration (which required a price row via `TrackedTickers ∩ MarketPriceHistory`)
excluded them. They are **real subjects**, not fabrications, and remain in the
compatibility population with NULL market inputs:

| legacy CompanyID | name |
| --- | --- |
| `09029850a7825c34a7c8958a08fcdf26` | خبهن |
| `326f53e9133b7e24c3b9ffec1e73fa18` | خاهن |
| `6081d3f368b7889ba242435db91b5b2f` | شکیمیا |
| `857898d4f504279f0355b95477392169` | ولشرق |
| `9ec90a47014c21843c4239f7a99a76f1` | شخارک |

## The 2 canonical-only funds

`مثقال`, `یاقوت` exist in canonical + `TrackedTickers`/`MarketPriceHistory` only.
They are **not** v3.7 scoring subjects and are absent from the compatibility model.

## Compatibility subject identity

`legacy_subject_id = "legacy:<legacy CompanyID>"` — stable, derived from the exact
legacy subject identity used by v3.7. It is **not** a canonical UUID and never
creates a canonical entity.

`analytics_parity_debug/v37_scoring_subjects.csv` holds one row per subject with
legacy id/name/symbol/instrument, nullable canonical mapping, data-availability
flags, origin, notes.

## Many-to-one mapping (allowed, no duplicate canonical entities)

`کاتالیست‌های صنعتی آریا` (کسرا) has two legacy CompanyIDs
(`7e41b7fd…`, `4ccc9664…`) mapping to one canonical company/security. Only
`7e41b7fd…` appears in v3.7; `4ccc9664…` is mapped but not a v3.7 scoring subject.
Because the canonical security merges both CompanyIDs' price rows, the compatibility
oracle uses the **per-legacy-CompanyID** frozen market snapshot (see below), which
is why the isolated model is required for exact parity.

## Exact population assertion

`build_v37_compat_population.py` writes `analytics_parity_debug/population_exact_diff.csv`
and asserts:

```
v3.7 subjects            = 276
compat_v37 subjects      = 276
only_in_sqlserver        = 0
only_in_compat           = 0
POPULATION_PARITY_PASS
```

Shadow model: `compat_v37.scoring_subjects` on
`company_financial_analytics_shadow_v121`.
**COMPATIBILITY_ONLY_NOT_CANONICAL** — disposable, not part of Canonical PostgreSQL v1.2.1.
