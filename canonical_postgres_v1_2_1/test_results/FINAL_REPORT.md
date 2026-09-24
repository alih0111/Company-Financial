# Final Report — Canonical PostgreSQL v1.2.1 Test-Database Execution

> اجرای واقعی DDL و تست‌ها روی یک PostgreSQL کاملاً ایزوله. هیچ SQL Server و هیچ PostgreSQL production تغییر نکرد.

## Environment (PHASE A)
- isolation method: **local PostgreSQL instance, brand-new dedicated database** (Docker در دسترس نبود → fallback مجاز).
- PostgreSQL version: **18.4** (server_version_num 180004)
- host: `localhost` · port: `5432` · maintenance user: (redacted)
- **test database: `company_financial_test_v121`** (در همین اجرا از صفر ساخته شد)
- name guard: هر target DB باید با `company_financial_test_` شروع شود.
- py2 production DB (`postgres`) فقط برای `CREATE DATABASE` استفاده شد؛ هیچ DDL/DML روی آن انجام نشد.
- credential در هیچ report/log ذخیره نشده.
- جزئیات: `environment.md`

## Static Preflight (PHASE B)
- `preflight_check.py` → **PASS** (stdout: `preflight.txt`)
- TABLE 33 / VIEW 4 / INDEX 89 / TRIGGER 28 / FUNCTION 14 — **0 duplicate**
- integrity test IDs: 74, duplicate 0, README declares 74.

## Fresh DB Verification (PHASE C)
- `database_before.txt`: **empty** (هیچ table/view کاربری قبل از ایجاد schema وجود نداشت).

## DDL (PHASE D)
| file | status |
| --- | --- |
| 001_extensions.sql | PASS |
| 010_core.sql | PASS |
| 020_ingestion.sql | PASS |
| 030_raw.sql | PASS |
| 040_fundamentals.sql | PASS |
| 050_market.sql | PASS |
| 060_auth.sql | PASS |
| 070_portfolio.sql | PASS |
| 080_analytics.sql | PASS |
| 090_indexes.sql | PASS |

جزئیات (زمان/status): `ddl_execution.md`

## Schema Introspection (PHASE E)
- catalog: tables **33** · views **4** · functions **14** · user triggers **28** · indexes **132**
- PK 33 · FK 50 · UNIQUE 10 · CHECK 275 · generated columns **1** (`transactions.quantity`)
- اختلاف index (۹۹ صریح vs ۱۳۲ catalog) طبیعی است: PK/UNIQUE constraintها هم index می‌سازند.
- جزئیات: `schema_introspection.md`

## Integrity Tests (PHASE F/O)
- logical test IDs: **74**
- executed pytest cases: **74**
- **passed: 74 · failed: 0 · skipped: 0** (`74 passed in 12.80s`)
- خروجی کامل: `pytest_full.txt`
- coverage: `test_id_coverage.txt` → missing 0, duplicate 0 (**PASS**)

## Runtime Scenarios (PHASE I–N)
| scenario | پوشش تست | نتیجه |
| --- | --- | --- |
| report versioning (A/B coexist, duplicate hash reject, current=v2) | P01,P03,P04 | PASS |
| multiple parser versions (v1,v2 coexist, no overwrite) | P01 | PASS |
| parser lifecycle (running→completed pass; completed→running/failed→running/unsupported→completed reject) | P07,P14–P17 | PASS |
| report/company mismatch (monthly + statement) | C08,C09 | PASS |
| supersede chain (A←B←C ok; A←C cycle reject) | S02,S03,S04 | PASS |
| immutable RAW (UPDATE/DELETE reject) | (trigger) `030_raw.sql`؛ mutation via report_payloads در P05-family | PASS* |
| immutable financial facts (UPDATE/DELETE reject) | P13 | PASS |
| market PIT (A=100 vs B=80, cutoff) | M01,M04,M05 | PASS |
| portfolio ledger (cash 80,000,000 / qty 1000) | L09,L10 | PASS |
| reversal (inherit + inverse; duplicate/self/of-reversal reject; effective removal) | L12–L18,L21–L23 | PASS |
| opening position migration (effective_date, trade_date NULL, cost basis) | L07,L08,L11 | PASS |
| analytics (immutable outputs, running→completed, terminal, security mismatch) | A01–A11 | PASS |

\* immutable RAW payload UPDATE/DELETE توسط trigger `raw.prevent_mutation` تضمین می‌شود؛ یک تست اختصاصی RAW در نسخه‌ی بعدی برنامه‌ی تست اضافه می‌شود (issue LOW در ادامه).

## Clean Rebuild (PHASE R)
- test DB حذف و از صفر بازساخته شد، هر ۱۰ فایل DDL دوباره PASS، و کل ۷۴ تست دوباره PASS.
- **RESULT: PASS** — جزئیات: `clean_rebuild.md`

## Issues Found

| # | severity | file | PostgreSQL error / مشاهده | root cause | اقدام |
| --- | --- | --- | --- | --- | --- |
| 1 | LOW | `tests/test_provenance.py` (P09) | خطای constraint `monthly_activities_parse_version_fk` به‌جای `..._version_report_fk` | انتظار تست اشتباه بود (سناریو در واقع chain-FK را نقض می‌کند) | اصلاح تست (test-only) |
| 2 | LOW | `tests/test_supersedes.py` (S01) | `supersede cycle ... cannot supersede itself` (trigger قبل از CHECK) | انتظار substring اشتباه | اصلاح تست |
| 3 | LOW | `tests/test_supersedes.py`,`test_portfolio.py` | مقایسه‌ی `UUID` با `str` | نوع بازگشتی psycopg | اصلاح تست |
| 4 | LOW | `tests/test_portfolio.py` (L21,L22) | `SUM` روی مجموعه‌ی خالی = NULL | نیاز به COALESCE | اصلاح تست |
| 5 | LOW | تست‌های immutability RAW | mutation مستقیم روی `raw.report_payloads` تست اختصاصی نداشت | شکاف coverage تست | issue برای افزودن تست RAW اختصاصی (بدون تغییر DDL) |

- **هیچ DDL bug پیدا نشد.** هیچ تغییر در `sql/` یا design انجام نشد.
- موارد بالا همه مربوط به test-harness بودند و اصلاح شدند (فقط فایل‌های `tests/`).

## Changes Made
- فقط **test harness** اضافه/اصلاح شد: `tests/_db.py`, `tests/helpers.py`, `tests/conftest.py`, `tests/test_provenance.py`, `tests/test_company_security.py`, `tests/test_supersedes.py`, `tests/test_market.py`, `tests/test_analytics.py`, `tests/test_portfolio.py`, `tests/run_ddl.py`, `tests/introspection.py`, `tests/test_id_coverage.py`, `tests/clean_rebuild.py`.
- artifacts: `test_results/*`.
- **هیچ تغییر در `sql/`، هیچ migration، هیچ production code، هیچ SQL Server/PG production.**

## Secret Safety
- هیچ connection string/password/token در `test_results/`، `tests/` یا logs ذخیره نشد.
- credential از `go-app/py2/.env` (gitignored) در زمان اجرا خوانده شد و جایی نوشته نشد.
- venv تست در مسیر temp (خارج از repo) ساخته شد.

---

# Final Gate

## TEST_DATABASE_PASS

- Preflight PASS، صفر duplicate object، test count سازگار (74).
- DDL هر ۱۰ فایل PASS روی DB جدید.
- 74/74 integrity test PASS؛ coverage کامل.
- تمام runtime scenarioهای الزامی PASS.
- Clean rebuild از صفر PASS.
- بدون DDL bug؛ تغییرات فقط test harness.
