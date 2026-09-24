# Legacy Heuristic Audit (v3.7)

هدف: parity با legacy ≠ کپی technical debt به مدل جدید.

| heuristic | چرا در SQL Server لازم بود | canonical چه چیزی را اصلاح کرد | در compat layer لازم است؟ | در canonical future |
| --- | --- | --- | --- | --- |
| `NPUnitRatio` (توان-۱۰ بین NetProfitAmount و Product1) | `Product1 = EPS × Capital` مقیاس مخلوط داشت | `net_profit` و `eps` جدا و واحددار (rial / rial_per_share) ذخیره شدند | **خیر** — در compat از canonical net_profit استفاده شد | حذف شود |
| `OpK` / تشخیص per-share | `OperatingProfitNew` گاهی per-share و گاهی مبلغی بود | `operating_profit` همیشه rial ذخیره می‌شود | **خیر** | حذف شود |
| `OpAbs` / `OpAmt` / `OpLYAmt` / `OpFYPrevAmt` | هم‌واحد کردن سود عملیاتی با Revenue/FinanceCosts | یکسان‌سازی واحد در ingestion | **خیر** | حذف شود |
| `Product1/2/3` | مشتق EPS×Capital | عمداً به‌عنوان fact منتقل **نشد** (LEGACY_DERIVED_DO_NOT_MIGRATE_AS_FACT) | **خیر** | حذف |
| `TTMEPS` ضرب/تقسیم دستی | اختلاف مقیاس TTM و EPS | shares از `capital/1000` و TTM از facts | تا حدی (محاسبه‌ی shares) | با ستون shares صریح ساده شود |
| `DataQualityScore` با `GETDATE()` + offset 621/622 | نبود تاریخ میلادی/cutoff | `date` میلادی + `source_cutoff_at` | **خیر** (cutoff صریح) | حذف |

## نتیجه
compat layer **نباید** این heuristicها را به canonical data بریزد؛ در implementation فقط از داده‌ی canonical استفاده شد. اختلاف‌های مشاهده‌شده در `TTMNetProfit` و `QuantScore` به همین حذف heuristicها و کامل‌نبودن بازتولید rankها برمی‌گردد، نه به canonical data.
