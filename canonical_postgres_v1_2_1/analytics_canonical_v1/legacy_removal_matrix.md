# Canonical v1 — Legacy Heuristic Removal Matrix

Every legacy v3.7 heuristic and its canonical v1 replacement. Canonical v1 must
contain **none** of the left column.

| Legacy logic | Why it existed | Canonical replacement |
| --- | --- | --- |
| `Product1` (= mixed-scale `EPS × capital`) | legacy `miandore2` stored net profit in a product column | direct `fundamentals.financial_facts(net_profit)` with `canonical_unit = rial` |
| `Product2` / `Product3` | prior-period products | canonical `period_order 2/3` facts |
| `NPUnitRatio` | reconciled inconsistent units between amount and Product1 | not needed: all monetary facts are canonical IRR |
| `OpK` | `OperatingProfitNew` was sometimes per-share, sometimes absolute | not needed: `operating_profit` fact is canonical IRR |
| `OpAmt` / `OpLYAmt` / `OpFYPrevAmt` | reconstructed amount-scale operating profit | canonical `operating_profit` TTM |
| `OpAbs` / `OpLYAbs` | per-share-normalized operating profit (Product1 scale) | canonical `operating_profit` TTM |
| `Num1_Value*` | legacy EPS slots | canonical `eps` facts |
| `Num2_Value*` | legacy capital/share-count slots (mixed) | canonical `capital` fact; share count only if needed and well-defined |
| `TTMEPS` product path (`SR_TTM × EPS / NetProfitAmount`) | EPS reconstruction via mixed columns | canonical `eps` TTM |
| `SalesGrowth` windowing by `fn_JalaliKey` | legacy jalali keys | canonical `period_end_date` + `fiscal_year`/`fiscal_month` |
| `GETDATE()` + 621/622 offset staleness | no canonical cutoff | explicit `as_of_date` + `source_cutoff_at` |
| DataQualityScore from `GETDATE()` freshness | runtime clock coupling | DQ from canonical `collected_at`/`published_at` vs cutoff (see `data_quality.md`) |
| Product1-based PE fallback | legacy net-profit scale | canonical `price / eps_ttm`; NULL if `eps_ttm` missing |
| `OtherNonOpNew` / `FinanceCostsNew` raw columns | legacy column semantics | canonical `other_non_operating` / `finance_cost` facts |
| `CASE` unit guards (±200%, ±100×, 3× revenue) | masked mixed units | removed; unit correctness enforced upstream; only economically meaningful guards remain (e.g. PE range) |

## Rule

If a required canonical fact is missing, canonical v1 emits a Data Quality issue
and sets the affected metric to `NULL`. It must **not** reconstruct the value from
legacy-shaped columns or from `EPS × capital`.
