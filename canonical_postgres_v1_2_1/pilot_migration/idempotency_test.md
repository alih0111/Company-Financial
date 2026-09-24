# Idempotency Test

## Method
- Migration tool با همان `sample_companies.json` چند بار روی همان pilot DB اجرا شد.
- قبل و بعد از اجرا، counts تمام جدول‌های هدف با `migration_tools/counts.py` snapshot شد.
- سیاست upsert: `ON CONFLICT DO NOTHING` برای جدول‌های immutable (report_versions، financial_facts، monthly_activities، price_observations) و upsert کنترل‌شده (company/security/report/parse_run)؛ هیچ درج تکراری مجاز نیست.

## Result — run #2 (after initial commit)

Run اول (commit): counts پایه ثبت شد. سپس run دوم اجرا شد؛ خروجی per-company نشان داد:

```
[kastra] committed: reports=0 monthly=0 facts=257 prices=0
counters: {'ingestion.parse_runs': 826, 'ingestion.reports': 826}
```

نکته: `facts=257` شمارش **attempt** است (نه insert)؛ counter واقعی `fundamentals.financial_facts` در run دوم **0** بود (bump فقط روی insert واقعی). `monthly=0` و `prices=0` تأیید عدم درج.

## Result — run #3 (before/after counts)

| table | before run3 | after run3 | diff |
| --- | --- | --- | --- |
| core.companies | 8 | 8 | 0 |
| core.securities | 8 | 8 | 0 |
| core.security_aliases | 17 | 17 | 0 |
| core.legacy_entity_map | 52 | 52 | 0 |
| ingestion.reports | 826 | 826 | 0 |
| ingestion.report_versions | 826 | 826 | 0 |
| ingestion.parse_runs | 826 | 826 | 0 |
| fundamentals.monthly_activities | 594 | 594 | 0 |
| fundamentals.financial_statements | 236 | 236 | 0 |
| fundamentals.financial_facts | 2110 | 2110 | 0 |
| market.price_observations | 26595 | 26595 | 0 |

**IDEMPOTENCY DIFF: NONE — all table counts unchanged.**

## Conclusion
راه‌اندازی دوم/سوم هیچ duplicate company/security/report/activity/fact/price ایجاد نکرد؛ رکوردهای موجود به‌عنوان existing شناسایی و skip شدند. **PASS**.
