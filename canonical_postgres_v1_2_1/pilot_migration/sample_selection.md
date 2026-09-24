# Pilot Sample Selection

۸ شرکت از SQL Server انتخاب شدند تا نمونه عمداً heterogeneous باشد.
CompanyIDها همان `md5(name)` legacy هستند.

| # | label | symbol | legacy CompanyID(s) | criterion |
| --- | --- | --- | --- | --- |
| 1 | khodro | خودرو | `8f0d3b9ed3bb17e93db23268de21bd69` | identity ساده + price history طولانی (5288) + financials غیر-null |
| 2 | dekpesol | دکپسول | `d4ba95c595b08e7a8441a997f29f4427` | بیشترین تاریخچه‌ی mahane (79) |
| 3 | chekapa | چکاپا | `799566aa607bcd4a8ce4fed470c7d2b0` | بیشترین ردیف miandore2 (~30) |
| 4 | erafo | ارفع | `9f4709224be63e56349d1cc368e5f005` | financials غنی (دارایی/حقوق/جریان نقدی) + چند نوع صورت مالی |
| 5 | shekarbn | شکربن | `2dc3ef3ab0a0505e8859b5400fc35e95` | price history طولانی (5306) + NULL/data-quality (financials صفر/نال) |
| 6 | betrans | بترانس | `5846976e3619ada1281f076ebdce9055` | CodalReports با ۷ گزارش (correction candidate) |
| 7 | ofoq | افق | `3eed9ad615c315d96a80b4ed8599772d` | حجم بالای mahane (77) + financials غیر-null |
| 8 | kastra | کسرا | `4ccc9664a47539eaff4b6b34fbfc0931`, `7e41b7fd7ba1c353199eba22667db254` | **identity conflict شناخته‌شده**: دو legacy CompanyID با یک InstrumentCode `4614779520007780` |

## توضیح criterionهای خواسته‌شده
- **identity ساده بدون conflict:** khodro (یک CompanyID، یک ins، یک symbol).
- **تاریخچه‌ی زیاد mahane:** dekpesol (79) و ofoq (77).
- **چند گزارش miandore2:** chekapa (30) و اکثر نمونه‌ها (27–30).
- **price history طولانی:** shekarbn (5306) و khodro (5288).
- **report correction/version:** betrans (۷ گزارش Codal). توجه: این‌ها نسخه‌های مستقل Codal هستند نه `report_version` از یک source؛ در `report_versions` به‌صورت synthetic v1 ثبت شدند.
- **NULL/data quality issue:** shekarbn (financials عمدتاً NULL/zero) و dekpesol (TotalAssets/OCF خالی).
- **چند نوع صورت مالی:** erafo (income + balance sheet + cash flow).
- **identity conflict:** kastra.

## محدودیت‌های داده‌ای که در نمونه یافت نشد
- sample ای که *همان source report* را چند بار fetch کرده باشد (report_version واقعی > 1) در SQL Server وجود ندارد؛ همه‌ی گزارش‌های legacy تک‌نسخه‌اند → synthetic v1.
- `statements` legacy فقط برای یک شرکت (`کالا`) و با `UnitCode='unknown'` است؛ عمداً وارد sample نشد (خارج از دامنه‌ی pilot).

## انتظار برای kastra
اثبات اینکه دو legacy identity (`کاتالیست‌های صنعتی آریا` و `کسرا`) که یک InstrumentCode دارند، به **یک** canonical company/security converge شوند و duplicate company ساخته نشود. نتیجه در `identity_validation.md` (distinct canonical companies = 1).
