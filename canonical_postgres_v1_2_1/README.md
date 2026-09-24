# Canonical PostgreSQL Schema v1.2.1 (Pre-execution Patch)

> Patch محدود روی `canonical_postgres_v1_2/` برای رفع blockerهای static-review. نسخه‌های v1/v1.1/v1.2 دست‌نخورده‌اند.
> **هیچ DDL/migration اجرا نشده و هیچ production code تغییر نکرده است.**

## Blockerهای رفع‌شده
1. **Duplicate index:** `ix_price_observations_cutoff` فقط یک‌بار (در `050_market.sql`). تمام SQL برای duplicate object (table/view/index/trigger/function) اسکن شد → **صفر duplicate**.
2. **Test count:** شمارش دقیق = **74** (نه 52). marker `Test count (auto): 74`.
3. **Report→Company consistency:** `UNIQUE(id, company_id)` روی `ingestion.reports` + composite FK `(report_id, company_id)` در `monthly_activities`/`financial_statements`.
4. **parse_runs terminal lifecycle:** trigger state machine.
5. **score_runs terminal lifecycle:** trigger state machine.
6. **Reversal/cost-basis:** trigger حالا `participant_id` و `cost_basis_rial` را هم inherit/negate می‌کند + view `portfolio.effective_transactions` برای pair-cancellation.
7. **Quantity drift:** `quantity` حالا ستون **generated** = `abs(quantity_delta)`.
8. **observation_hash scope:** uniqueness scoped به `(security_id, trade_date, source, price_series, observation_hash)`.
9. **daily_prices policy:** مستند و deterministic (latest adjusted، tie-break با id).
10. **preflight_check.py:** اسکریپت read-only بدون DB.
11. **Test count خودکار:** از preflight.

## ساختار
```
canonical_postgres_v1_2_1/
  README.md  schema.md  erd.md  v1_2_to_v1_2_1_changes.md
  integrity_test_plan.md  legacy_to_v1_mapping.md  miandore2_fact_mapping.md
  v37_compatibility.md  sqlalchemy_model_plan.md  migration_plan.md
  validation_plan.md  preflight_check.py
  sql/ 001..090 (۱۰ فایل)
```

## اجرای preflight
```powershell
python canonical_postgres_v1_2_1/preflight_check.py
# PREFLIGHT: PASS  (exit 0)
```

## ترتیب اجرای SQL
`001 → 010 → 020 → 030 → 040 → 050 → 060 → 070 → 080 → 090`

Test count (auto): 74

---

# EXECUTION GATE

## READY_TO_CREATE_TEST_DATABASE

معیارها:
- `preflight_check.py` → **PASS** (صفر duplicate object، test count سازگار).
- صفر duplicate SQL object (table/view/index/trigger/function).
- Test count consistent: **74**.
- report/company integrity با composite FK رفع شد.
- terminal lifecycle برای parse_runs و score_runs enforce شد.
- reversal/cost-basis semantics با `effective_transactions` و negate کامل رفع شد.

گام بعدی (خارج از این مرحله): ساخت test database و اجرای DDL به ترتیب بالا، سپس `integrity_test_plan.md`.
