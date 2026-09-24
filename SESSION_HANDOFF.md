# SESSION HANDOFF — Company-Financial

> این فایل برای ادامه‌ی کار در یک OpenCode session جدید است. فرض: session جدید هیچ دسترسی به history قبلی ندارد.
> **هیچ credential/password/token در این فایل نیست.**

---

# 1. Project Goal

پروژه‌ی تحلیل بنیادی/تکنیکال شرکت‌های بورسی ایران با هدف:
- جمع‌آوری داده‌ی کدال (صورت‌های مالی، فعالیت ماهانه) و قیمت (BRS/TSETMC)
- امتیازدهی کمّی شرکت‌ها (نسخه‌ی فعلی: `vw_AIStockMetrics` v3.7 روی SQL Server)
- مهاجرت تدریجی از SQL Server legacy به یک **Canonical PostgreSQL Schema** با داده‌ی تمیز، واحددار، versioned و point-in-time-safe
- بازتولید parity با الگوریتم فعلی v3.7 به‌عنوان «oracle سازگاری»، سپس طراحی analytics آینده روی داده‌ی canonical

مسیر معماری هدف:
```
RAW (Codal payload) -> NORMALIZED (fundamentals/market) -> ANALYTICS (derived, versioned)
```

---

# 2. Current Architecture

- **React client** (`client/`): SPA با Vite/TS؛ API_BASE روی Go API؛ JWT در localStorage.
- **Go API** (`go-app/`, Gin): endpointها روی SQL Server `codal`؛ برخی endpointها اسکریپت‌های Python را اجرا می‌کنند.
- **Python ingestion** (`go-app/py/`): Playwright/pyodbc → SQL Server. و `go-app/py2/`: خط لوله‌ی نیمه‌کاره با SQLAlchemy/Alembic → PostgreSQL.
- **SQL Server legacy** (`codal`): منبع حقیقت فعلی؛ شامل `mahane`, `miandore2`, `MarketPriceHistory`, `CodalReports`, `CodalSyncState`, `TrackedTickers`, `FullPE`, `Users`, `Family*`, و view امتیازدهی.
- **PostgreSQL canonical target**: schema طراحی‌شده در `canonical_postgres_v1_2_1/` (نسخه‌ی نهایی طراحی) + دیتابیس‌های test/pilot/shadow برای اعتبارسنجی.

---

# 3. Completed Work (milestones به ترتیب)

| # | milestone | نتیجه | gate | artifact مهم |
| --- | --- | --- | --- | --- |
| 1 | `database_inventory` | استخراج read-only ساختار SQL Server | — | `database_inventory/README.md`, `extract_inventory.py`, `03_columns.md`, `05_indexes.md`, `14_source_usage.md` |
| 2 | `database_design_audit` | audit معنایی داده/کد | — | `database_design_audit/README.md`, `01..11_*.md` |
| 3 | `canonical_design_inputs` | حل ابهام‌های identity/unit/date/market/view-drift | READY | `canonical_design_inputs/README.md`, `01..07_*.md`, `sql/vw_AIStockMetrics_production.sql`, `company_identity_candidates.csv` |
| 4 | `canonical_postgres_v1` | طراحی اولیه schema | READY-to-implement | `canonical_postgres_v1/sql/001..090` |
| 5 | `canonical_postgres_v1_1` | hardening: version-aware، composite FK، immutable | READY_FOR_TEST_DATABASE | `..._v1_1/README.md`, `v1_to_v1_1_changes.md` |
| 6 | `canonical_postgres_v1_2` | final hardening: fetch/parse split، price revisioning، ledger semantics | READY_FOR_EXECUTABLE_TEST | `..._v1_2/README.md`, `v1_1_to_v1_2_changes.md` |
| 7 | `canonical_postgres_v1_2_1` | patch: duplicate index، report/company FK، terminal lifecycles، reversal/cost-basis، quantity derived | READY_TO_CREATE_TEST_DATABASE | `..._v1_2_1/README.md`, `v1_2_to_v1_2_1_changes.md`, `sql/`, `preflight_check.py` |
| 8 | executable test DB | اجرای واقعی schema + ۵۲→۷۴ تست | **TEST_DATABASE_PASS** | `.../test_results/FINAL_REPORT.md`, `tests/*` |
| 9 | pilot migration (۸ شرکت) | migration واقعی + validation | **PILOT_MIGRATION_PASS_WITH_KNOWN_LIMITATIONS** | `.../pilot_migration/FINAL_PILOT_REPORT.md`, `.../migration_tools/*` |
| 10 | full-universe shadow migration | کل universe به shadow DB | **FULL_UNIVERSE_INPUTS_PASS** | `.../analytics_parity/full_universe_migration_validation.md` |
| 11 | analytics parity attempt | بازسازی جزئی v3.7 و مقایسه | **ANALYTICS_PARITY_FAIL** | `.../analytics_parity/FINAL_ANALYTICS_PARITY_REPORT.md` |

---

# 4. Canonical PostgreSQL Status

- Schema: **`canonical_postgres_v1_2_1`**
- Status: **`TEST_DATABASE_PASS`**
- 10/10 DDL files PASS (001..090) روی دیتابیس جدید
- **74/74 integrity tests PASS** (0 failed, 0 skipped)
- clean rebuild PASS (drop+recreate+DDL+pytest)
- preflight PASS: 0 duplicate object (TABLE 33, VIEW 4, INDEX 89, TRIGGER 28, FUNCTION 14)
- جزئیات: `canonical_postgres_v1_2_1/test_results/FINAL_REPORT.md`

---

# 5. Pilot Migration Status

- Gate: **`PILOT_MIGRATION_PASS_WITH_KNOWN_LIMITATIONS`**
- ۸ شرکت: khodro, dekpesol, chekapa, erafo, shekarbn, betrans, ofoq, kastra (+ identity conflict)
- اعداد: monthly 594/594، facts 2110/2110 (۱ ردیف rounded ≤1e-6)، prices 26595/26595
- date 27189/27189، orphan=0، duplicate=0، unit ok
- idempotency PASS، rollback PASS (per-company transaction)
- محدودیت‌ها: گردکردن `numeric(30,6)`، `raw.report_payloads` خالی، cross-link CodalReports↔legacy reports انجام نشده، `--all` پیاده نشده، FullPE/analytics خارج از دامنه
- مسیر: `canonical_postgres_v1_2_1/pilot_migration/FINAL_PILOT_REPORT.md`

---

# 6. Full Universe Migration Status

- TrackedTickers = **282**
- reference v3.7 rows = **276**
- canonical analytics subjects فعلی = **273**
- canonical migration inputs **PASS**
- monthly = **12,004** (subset=12,075 ✓)
- financial facts = **71,361** (expected non-null mapped=71,361 ✓)
- market prices = **705,812** (= MPH ✓)
- orphan = 0، duplicate = 0، name-only identity = 0، duplicate ins = 0
- Gate: **`FULL_UNIVERSE_INPUTS_PASS`**
- مسیر: `canonical_postgres_v1_2_1/analytics_parity/full_universe_migration_validation.md`

---

# 7. Frozen Analytics Context

- `analysis_cutoff_at = 2026-09-24T20:41:02Z`
- `analysis_as_of_date = 2026-09-24`
- Production reference view: `dbo.vw_AIStockMetrics`
- ScoreVersion: `v3.7`
- Reference snapshot: `canonical_postgres_v1_2_1/analytics_parity/reference/v37_full_snapshot.csv` (276 rows × 94 cols)
- context JSON: `canonical_postgres_v1_2_1/analytics_parity/reference_context.json`
- **Production SQL snapshot (algorithm source of truth):** `canonical_design_inputs/sql/vw_AIStockMetrics_production.sql`
  (fایل repo `go-app/sql/vw_AIStockMetrics.sql` = v3.6 است و **مرجع نیست**)

---

# 8. Current Analytics Result

Gate: **`ANALYTICS_PARITY_FAIL`**

| metric | SQL Server | PG compat | mismatch |
| --- | --- | --- | --- |
| rows | 276 | 273 | population |
| SalesGrowth12M | — | — | **3** |
| NetProfitMargin12M | — | — | **18** |
| ROE | — | — | **16** |
| OperatingMargin12M | — | — | **136** |
| TTMNetProfit | — | — | **257** |
| PEApprox | — | — | **241** |
| QuantScore | — | — | **273 / 273** |

همچنین:
- canonical inputs **PASS**
- reproducibility **PASS** (hash یکسان)
- point-in-time **PASS** (observation بعد از cutoff = 0)
- هیچ `UNKNOWN` mismatch نیست (همه classification شده)
- **canonical data نباید برای imitation legacy heuristic تغییر کند**

مسیر: `canonical_postgres_v1_2_1/analytics_parity/FINAL_ANALYTICS_PARITY_REPORT.md`

---

# 9. Current Root Cause / Blocker

Blocker **مigration یا schema نیست** (آن‌ها PASS هستند). Blocker:

**Exact reconstruction of production v3.7 analytics:**
- population reconciliation (282 → 276 → 273)
- TTM logic دقیق
- همه‌ی ۱۹ فاکتور
- NULL semantics
- rank/percentile/tie semantics
- penalties
- QuantScore decomposition

compat فعلی یک reimplementation **reduced** است؛ زیرمجموعه‌ای از فاکتورها reproduce شده و بقیه neutral 0.3.

---

# 10. Important Architectural Rules

- **SQL Server is READ ONLY** (فقط SELECT؛ هیچ DML/DDL).
- production DB/code نباید تغییر کند.
- canonical fundamentals نباید با heuristicهای legacy آلوده شود.
- منطق `NPUnitRatio` / `OpK` / `OpAmt` / Product-derived فقط در `analytics_v37_compat` مجاز است، نه در canonical facts.
- **Company != Security** (ناشر ≠ ابزار قابل معامله).
- legacy scoring subject ممکن است با canonical company متفاوت باشد.
- **ممنوع:** ساخت شرکت canonical جعلی فقط برای بازتولید population v3.7.
- **v3.7 یک compatibility oracle است، نه معماری آینده.**

---

# 11. Databases

| database | نقش | وضعیت |
| --- | --- | --- |
| `company_financial_test_v121` | تست executable schema (74 تست) | **دست‌نخورده بماند** |
| `company_financial_migration_pilot_v121` | pilot 8-شرکتی | **دست‌نخورده بماند** |
| `company_financial_migration_pilot_rb` | rollback test (8-شرکتی) | می‌تواند دور ریخته شود |
| `company_financial_analytics_shadow_v121` | full universe + analytics compat + score_run | **مورد استفاده‌ی مرحله‌ی بعد** |

سرور: PostgreSQL محلی `localhost:5432` (نسخه‌ی 18.4)، maintenance user `postgres` (credential از `.env` در زمان اجرا خوانده می‌شود؛ اینجا نوشته نمی‌شود).
نام دیتابیس‌ها در `migration_tools/common.py` با guard پیشوندی محافظت می‌شوند:
`company_financial_test_`, `company_financial_migration_pilot_`, `company_financial_analytics_shadow_`.

---

# 12. Key Paths to Read First

- `SESSION_HANDOFF.md` (همین فایل)
- `canonical_postgres_v1_2_1/README.md`
- `canonical_postgres_v1_2_1/test_results/FINAL_REPORT.md`
- `canonical_postgres_v1_2_1/pilot_migration/FINAL_PILOT_REPORT.md`
- `canonical_postgres_v1_2_1/analytics_parity/FINAL_ANALYTICS_PARITY_REPORT.md`
- `canonical_postgres_v1_2_1/analytics_parity/population_validation.md`
- `canonical_postgres_v1_2_1/analytics_parity/metric_comparison.md`
- `canonical_postgres_v1_2_1/analytics_parity/factor_comparison.md`
- `canonical_postgres_v1_2_1/analytics_parity/quantscore_comparison.md`
- `canonical_postgres_v1_2_1/analytics_parity/legacy_heuristics.md`
- `canonical_postgres_v1_2_1/analytics_parity/tolerances.md`
- `canonical_design_inputs/sql/vw_AIStockMetrics_production.sql` (production v3.7 SQL)
- `canonical_postgres_v1_2_1/analytics_v37_compat/` (snapshot_reference.py, build_universe_manifest.py, full_universe_validate.py, compute_and_compare.py, gen_reports.py)
- `canonical_postgres_v1_2_1/migration_tools/` (common.py, create_pilot_db.py, pilot_migrate.py, counts.py, validate_pilot.py, smoke_pilot.py)
- `canonical_postgres_v1_2_1/sql/001..090` + `schema.md` + `erd.md`

---

# 13. Exact Next Task

Task بعدی: **`Exact v3.7 Compatibility Debugging`**

ترتیب کار (QuantScore باید **آخر** بیاید، نه اول):
1. reconcile population: 282 → 276 → 273 (تعیین دقیق eligibility/source selection)
2. استخراج intermediate stages از production v3.7 با queryهای diagnostic فقط-SELECT (بدون تغییر view)
3. حل `TTMNetProfit` parity
4. حل emulation `OperatingProfit` / `OperatingMargin` (legacy)
5. تثبیت base metric parity
6. حل valuation / `PEApprox`
7. استخراج specification دقیق همه‌ی ۱۹ فاکتور
8. بازتولید NULL/tie/rank/population semantics
9. factor-by-factor parity
10. penalties
11. QuantScore attribution (decompose differences)
12. final v3.7 parity gate

**ممنوع:** debug کردن QuantScore قبل از فاکتورها.

---

# 14. Safety

Session جدید نباید:
- production DB را تغییر دهد
- SQL Server را write کند
- canonical facts را patch کند
- identity canonical را duplicate کند
- بدون دلیل schema جدید بسازد

و باید: SQL Server = read-only؛ credential فقط از `.env`؛ هیچ secret در artifactها.

---

# 15. Uncommitted / Generated Files

`git status` فعلی (همه untracked؛ هیچ‌کدام commit نشده):
```
?? database_inventory/
?? database_design_audit/
?? canonical_design_inputs/   (+ canonical_design_inputs.zip)
?? canonical_postgres_v1/     (+ canonical_postgres_v1.zip)
?? canonical_postgres_v1_1/   (+ canonical_postgres_v1_1.zip)
?? canonical_postgres_v1_2/   (+ canonical_postgres_v1_2.zip)
?? canonical_postgres_v1_2_1/(+ canonical_postgres_v1_2_1.zip)
```
- `.zip`ها توسط کاربر ساخته شده‌اند (نه ابزار).
- `canonical_postgres_v1_2_1/.gitignore` شامل `.env`, `.env.*`, `.venv_test/`, `__pycache__/`, `.pytest_cache/`.
- هیچ credential commit نشده؛ `.env`ها در `.gitignore` ریشه هستند.

---

# 16. Commands / Environment

**Python test venv (خارج از repo، ephemeral):**
`C:\Users\aliheyd\AppData\Local\Temp\opencode\pgtest_venv\Scripts\python.exe`
نصب‌شده: `psycopg[binary]`, `pyodbc`, `pytest`, `python-dotenv`, `jdatetime`.
Global python: `Python 3.13.5` (فقط `python-dotenv` دارد).

**اتصال PostgreSQL:** credential از `go-app/py2/.env` (`DATABASE_URL`) و `go-app/.env` خوانده می‌شود. helper: `canonical_postgres_v1_2_1/migration_tools/common.py` (`pg_pilot_conn`, `sqlserver_conn`).
برای کار روی shadow DB متغیر محیطی را ست کن:
```powershell
$env:CDF_PILOT_DB="company_financial_analytics_shadow_v121"
```

**تست‌های schema (test DB):**
```powershell
$py = "C:\Users\aliheyd\AppData\Local\Temp\opencode\pgtest_venv\Scripts\python.exe"
& $py -m pytest canonical_postgres_v1_2_1\tests -q
```

**Analytics compat:**
```powershell
$env:CDF_PILOT_DB="company_financial_analytics_shadow_v121"
& $py canonical_postgres_v1_2_1\analytics_v37_compat\snapshot_reference.py
& $py canonical_postgres_v1_2_1\analytics_v37_compat\build_universe_manifest.py
& $py canonical_postgres_v1_2_1\analytics_v37_compat\full_universe_validate.py
& $py canonical_postgres_v1_2_1\analytics_v37_compat\compute_and_compare.py
& $py canonical_postgres_v1_2_1\analytics_v37_compat\gen_reports.py
& $py -m pytest canonical_postgres_v1_2_1\analytics_parity\tests -q
```

**preflight:**
```powershell
python canonical_postgres_v1_2_1\preflight_check.py
```

**ایمنی:** هیچ credential در دستورها hardcode نشود؛ فقط از `.env` خوانده شود. `psql` مسیر: `C:\Program Files\PostgreSQL\18\bin\psql.exe`.

---

NEXT_SESSION_READY = YES
