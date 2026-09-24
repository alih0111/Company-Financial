# 11 — Unknowns

> فهرست مواردی که از روی کد **با اطمینان مشخص نشدند**. عمداً حدس نزده شده است.
> این موارد باید پیش از طراحی نهایی PostgreSQL روشن شوند.

## Identity

1. در داده‌ی فعلی، `mahane`/`miandore2` با `CompanyID = md5(نام کامل)` پر شده‌اند یا `md5(نماد)`؟ (مسیر legacy vs sync). نیاز به query داده.
2. آیا `CompanyName` در `MarketPriceHistory` همیشه نام codal است یا می‌تواند نماد باشد؟
3. نگاشت کامل `Symbol ↔ CompanyID ↔ InstrumentCode` در داده‌ی موجود چیست و چند شرکت unmapped مانده‌اند؟

## Units

4. واحد واقعی `mahane.Value1/Value2/Value3`.
5. واحد واقعی `miandore2`: `capital`, `OperatingProfitNew`, `RevenueNew`, `NetProfitAmount`, `TotalAssets`, `OperatingCashFlow` (ریال؟ هزار ریال؟ میلیون ریال؟).
6. واحد `BIGINT` قیمت‌های `MarketPriceHistory` (ریال یا تومان).
7. آیا `NetProfitAmount` صراحتاً «میلیون ریال» است (فرض داخل view) یا واحد دیگری.

## Tables / Origin

8. **نویسنده و منبع `dbo.StockData`** — هیچ writer در سورس نیست.
9. **نویسنده و منبع `dbo.StockPrices`** — هیچ writer/reader نیست.
10. **منبع و نویسنده‌ی `dbo.statements`** — هیچ ارجاعی در سورس نیست (نه CREATE، نه INSERT).
11. **نویسنده و معنای `mahane.LastModificationDate`**.
12. آیا scriptهای خارج از ریپو (خارج از `go-app/`) روی `codal` می‌نویسند؟

## Market / Corporate Actions

13. آیا `py/price.py` قیمت‌ها را تعدیل می‌کند یا خام ذخیره می‌کند؟
14. الگوریتم دقیق `local_adjust_prices` برای رویدادهای شرکتی و صحت آن.
15. آیا `FirstPrice` در `MarketPriceHistory` جایگزین قابل‌اعتماد `Open` در `StockData` است؟
16. تفاوت داده‌ی `brs_prices.py` و `price.py` روی یک ردیف مشابه `(InstrumentCode, GregorianDate)` چقدر است؟ (هر دو MERGE می‌کنند.)

## View / Scoring

17. کدام fallbackهای `SR_TTM*` در داده‌ی واقعی فعال‌اند.
18. مقادیر دقیق همه‌ی آستانه‌های penalty در `vw_AIStockMetrics` (نیاز به خواندن کامل توابع درون view).
19. آیا `vw_AIStockMetrics` نصب‌شده (v3.7) و `go-app/sql` (v3.6) از نظر خروجی تفاوت معنادار دارند؟ (drift نسخه).
20. منبع مقادیر رتبه‌ی خنثای پیش‌فرض (0.3/0.5) و اینکه آیا داده‌ی کافی برای رتبه‌ی واقعی وجود دارد.

## Users / Family

21. ساختار دقیق JSON داخل `Users.Portfolio` و `Users.ViewedItems` در همه‌ی رکوردها (schema پایدار نیست).
22. آیا `Family*` از Excel مهاجرت شده و آیا با `Users.Portfolio` هم‌پوشانی/تناقض دارد؟

## Date / Timezone

23. منطقه‌ی زمانی واقعی مقادیر `datetime2` موجود (UTC یا local) در داده‌ی فعلی.
24. آیا `statements.CollectedAt` با `sysdatetime()` (local) یا UTC پر شده.

## py2

25. آیا `py2` واقعاً در production اجرا می‌شود یا پایلوت است؟ (هیچ endpoint/زمان‌بندی در Go برای آن نیست.)
26. چرا `companies.symbol`/`instrument_code` پر نمی‌شوند؛ آیا طراحی نیمه‌کاره است؟
