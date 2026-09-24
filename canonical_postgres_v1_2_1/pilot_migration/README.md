# Pilot Data Migration — README

انتقال واقعی و محدود داده از SQL Server (READ ONLY) به یک PostgreSQL pilot مستقل + مقایسه‌ی عددی Old vs New.

## دامنه
- **مدار:** SQL Server فقط SELECT؛ PostgreSQL فقط روی database مجزا.
- **دامنه‌ی pilot:** identity → reports → monthly → financials → market.
- **خارج از دامنه:** Users/Family/portfolio/auth/StockData/StockPrices/miandore/statements، و هیچ analytics (QuantScore/TTM/…).

## Databaseها
| db | نقش |
| --- | --- |
| `company_financial_migration_pilot_v121` | migration اصلی pilot (schema v1.2.1 + داده‌ی ۸ شرکت) |
| `company_financial_migration_pilot_rb` | rollback/failure test (کنار گذاشته‌شده) |
| `company_financial_test_v121` | تست schema قبلی؛ دست‌نخورده |

## Sample (۸ شرکت)
khodro, dekpesol, chekapa, erafo, shekarbn, betrans, ofoq, **kastra** — جزئیات در `sample_selection.md`.

## ابزارها (`../migration_tools/`)
| file | کار |
| --- | --- |
| `common.py` | اتصال read-only SQL Server + اتصال guard‌دار PG + jalali/obs_hash helpers |
| `create_pilot_db.py` | ساخت/recreate دیتابیس pilot + اعمال ۱۰ فایل schema |
| `pilot_migrate.py` | migration اصلی (sample-file اجباری، `--dry-run`، `--inject-failure`، تراکنش per-company) |
| `counts.py` | snapshot شمارش جدول‌ها |
| `validate_pilot.py` | تمام validationهای عددی Old vs New |
| `smoke_pilot.py` | smoke test حداقلی schema (rollback) |
| `profile_candidates.py` | profiling read-only برای انتخاب sample |
| `sample_companies.json` | فهرست نمونه |

## اجرای مجدد
```powershell
$py = "<venv>\Scripts\python.exe"
& $py migration_tools/create_pilot_db.py --recreate
& $py migration_tools/pilot_migrate.py --sample-file migration_tools/sample_companies.json
& $py migration_tools/validate_pilot.py
```

## نتایج (خلاصه)
- DDL: ۱۰/۱۰ PASS · Smoke: PASS
- identity: duplicate ins=0 · kastra convergence=1 · name-only=0
- row counts: همه اختلاف‌ها=0 (شامل price dedup)
- monthly: 594/594 · financial: 2110/2110 (in tolerance) · market: 160/160 exact
- date: 27189/27189 · unit: canonical != rial = 0 · orphan/duplicate = 0
- idempotency: بدون تغییر · rollback test: PASS

گزارش کامل: `FINAL_PILOT_REPORT.md` · issues: `issues.md`.
