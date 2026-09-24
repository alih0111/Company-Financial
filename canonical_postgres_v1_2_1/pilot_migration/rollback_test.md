# Failure / Rollback Test

## Transaction strategy
- **Transaction per company.** هر شرکت در یک تراکنش PostgreSQL مستقل پردازش می‌شود؛ در صورت خطا، همان شرکت rollback و بقیه ادامه می‌یابند.
- دلیل: مرز معنایی روشن (identity + reports + normalized + market یک شرکت)، جلوگیری از half-migrated state، و امکان ادامه‌ی migration بدون تکرار کل run.
- FKهای cross-company وجود ندارد (هر ردیف به company/security خودش وصل است)، پس rollback یک شرکت نمی‌تواند ناسازگاری cross-company بسازد.

## Method
- یک database مستقل و disposable ساخته شد: `company_financial_migration_pilot_rb`.
- schema از صفر اعمال شد (۱۰ فایل، PASS).
- migration با `--inject-failure 8f0d3b9ed3bb17e93db23268de21bd69` (khodro) اجرا شد؛ trigger خطا **بعد از** ساخت identity و **قبل از** درج domain data رخ می‌دهد تا rollback کامل شرکت تست شود.

## Result
```
[khodro] ROLLED BACK: injected failure for khodro
...
[kastra] committed: ...
issues: 1
```

| check | expected | actual |
| --- | --- | --- |
| khodro security present (ins=65883838195688438) | 0 | **0** |
| shekarbn security present (ins=27308217070238237) | 1 | **1** |
| core.companies | 7 | **7** |
| fundamentals.monthly_activities | >0 | **532** |
| market.price_observations | >0 | **21307** |

شرکت خرابکارانه‌fail‌شده **هیچ** اثر جزئی (company/security/report/monthly/fact/price) باقی نگذاشت؛ ۷ شرکت دیگر کامل commit شدند.

## Conclusion
Failure یک شرکت باعث half-migrated inconsistent state نشد. **PASS**.
