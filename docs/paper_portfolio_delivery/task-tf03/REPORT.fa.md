# TF-03 — تکمیل محدود پس از بازبینی lifecycle

نتیجهٔ کل: **PARTIAL**. اتصال wrapper، ممیزی و بازاجرایی آفلاین اصلاح و پذیرش شده‌اند؛ پیش‌نمایش سفارش زنده و آمادگی شروع همچنان BLOCKED هستند. هیچ ranking واقعی، حساب اصلی، O00، scheduler، P1/P3 یا raw زنده‌ای در این تکمیل تغییر نکرد.

## پذیرش lifecycle آفلاین — PASS

Harness بازاجراشدنی زیر main guard است و `--output-dir` صریح می‌گیرد؛ import آن اجرا ایجاد نمی‌کند، مقصد غیرخالی را رد می‌کند و پیش‌فرض آن پوشهٔ invocation یکتای scratch زیر repo است. regressionها خروجی را در `scratch-runs/` و pytest basetemp یکتا ذخیره می‌کنند. خروجی تحویل قدیمی در `offline/` هر ۱۲۸ فایلش حفظ شد.

چرخهٔ ۲۵ subprocess واقعی شامل ثبت تصمیم مصنوعی، preview، apply یک‌باره، replay پیش و پس از mark و مسیرهای خطا بود. socketهای childهای Python مسدود و ورودی‌ها synthetic بودند؛ شبکه و endpoint تازه مصرف نشد. پنج کنترل wrapper/cycle در evidence نهایی، preview سالم، `NO_NEW_SESSION`، hash مردود، کیفیت مردود و provider ناسازگار را پوشش می‌دهند. خروجی هر preview یک expected outcome دقیق دارد؛ `NO_NEW_SESSION` با session_count=0 و بدون fill/event کنترل شده است. همهٔ سناریوهای preview bytes حساب را ثابت گذاشتند.

دو harness متوالی در `scratch-runs/final-harness-4` و `final-harness-5` PASS شدند. SHA-256 evidence اجرای اول پس از اجرای دوم و pytest ثابت ماند: `790fce0165e068e2a93d02019b160a31eec390afe2b955a3423191ed3935eeae`. اجرای اول و دوم به‌ترتیب ۲۵ subprocess و حساب‌های temp با SHA-256 `4083f4b95c9f157b497612e81b948f524a3a9103b6cc077c6d69d8eea9f5d055` و `dcfedfe5575a23ad74cf8711c938d0a86a9ae1177635e15a88817cd3c9a88fe8` داشتند.

حسابداری مستقل با Decimal و ROUND_HALF_UP با snapshot نهایی تطبیق داده شد: ۸۰۶ سهم، gross=۹۹٬۴۶۰، fee=۴۹۷، نقد=۴۳، NAV زمان fill=۹۹٬۵۰۳، P&L زمان fill=-۴۹۷. mark در ۱۲۴۰ ریال ارزش دارایی ۹۹٬۹۴۴، NAV=۹۹٬۹۸۷ و P&L=-۱۳ داد. replay روز بعد از CLI با ساعت واقعی سیستم انجام شد؛ ساعت خرید به فرمان replay تزریق نشد و receipt و mark حفظ شدند.

## اتصال wrapper و نتیجهٔ محصول — PASS با خروجی صریح

در provider عمومی، manifest و hash صریح invocation اولویت قطعی دارند؛ وجود `TSETMC_CALENDAR_MANIFEST` ناسازگار در environment این انتخاب را عوض نکرد. fallback متغیر محیطی فقط در مسیر legacy `nscstart` و وقتی manifest صریح وجود ندارد باقی است. public مسیر NSCStart یا token را نمی‌خواند. در اجرای ایزولهٔ بدون EvidenceManifest، wrapper پیش از اجرای collector با `ISOLATED_ORDER_REVIEW_REQUIRES_EXPLICIT_EVIDENCE_MANIFEST` رد می‌کند؛ مقصدهای account، output و public-output همگی در تشخیص ایزوله لحاظ می‌شوند.

خروجی PowerShell و cycle اکنون outcome محصول، exit code فرزند و validation outcome را جدا ثبت می‌کند. preview سالم `PREVIEW_COMPLETE`، نبود جلسه `NO_NEW_SESSION` و ردهای hash/provider/quality `BLOCKED_VALIDATION_REFUSAL` هستند. علت validation در JSON نهایی باقی می‌ماند؛ موفقیت فرایند wrapper به‌تنهایی PASS محصول شمرده نمی‌شود. برچسب public همچنان فرض عملیاتی نسخه‌دار است و تقویم را رسمی/کامل اعلام نمی‌کند.

## اتصال گزارش و ممیزی نوشتن — PASS

mark، hash و source path حساب انتخاب‌شده را ثبت می‌کند؛ گزارش پس از mark به SHA snapshot نوشته‌شدهٔ همان حساب متصل است. status هش ranking پین‌شدهٔ حساب temp را با مسیر منشأ آن گزارش می‌کند و ranking عمومی اصلی را فقط در فیلد مستقل `reference_public_ranking` نگه می‌دارد.

ممیزی پیش/پس از اجرای نهایی ۹ مقصد واقعی/default، شامل کل `ranking_research/output/paper_cycle` (۵٬۹۴۸ فایل)، قواعد/evidence default، `client/public/research/v12-38`، مقاصد mark در `client/public/research/v12-36` و account/ranking اصلی را پوشش داد؛ همهٔ hashها و تعداد فایل‌ها برابر ماندند. ۱۲۸ فایل شواهد offline تحویل و دو فایل اصلی account/ranking نیز ثابت ماندند. شواهد در `evidence/write-target-audit.json` است. تغییرهای هم‌زمان UI، ingestion و `.gitignore` در checkout مستقل‌اند و به TF-03 نسبت داده نمی‌شوند.

## اجرای آزمون‌ها و دامنهٔ crash/concurrency

پس از آخرین تغییر، suite کامل **۱۷۱ passed، ۰ failed** در ۵۳۶٫۶۳ ثانیه اجرا شد؛ فرمان و فهرست فایل‌ها در `evidence/test-run.json` ثبت شده است. crash regressionها سه نقطهٔ write/pre-replace/post-replace برای writer اتمیک و crash واقعی subprocess در fill پس از replace را پوشش می‌دهند؛ recovery و replay بدون debit دوم بررسی می‌شوند. concurrency regressionها دو writer اتمیک و دو fill هم‌زمان را بررسی می‌کنند. این crash injectionها به wrapper نسبت داده نمی‌شوند.

## پیش‌نمایش زنده و آمادگی شروع — BLOCKED

- **live preview:** اجرا نشد؛ هیچ token یا live fetch تازه‌ای برای این اصلاحات مصرف نشد. capture زندهٔ موجود و rawها حفظ شدند.
- **آمادگی شروع:** BLOCKED به علت ranking با وضعیت `PREPARATION_UNCONFIRMED`؛ این تغییرات ranking را ارتقا نمی‌دهند.
- **حساب اصلی، scheduler و دفتر رسمی:** غیرفعال/دست‌نخورده؛ هش حساب اصلی در audit برابر baseline است.

Runbook ترتیب زمانی را اصلاح می‌کند: مدرک پایهٔ ثبت تصمیم از market evidence جداست، تصمیم با زمان واقعی ثبت می‌شود و فقط سپس acquisition تازه و preview انجام می‌شود. `NO_NEW_SESSION` نتیجهٔ طبیعی است و باید تا جلسهٔ بعد انتظار کشید. گزارش/نتیجهٔ پیشین پیش از به‌روزرسانی در `history/TF03-PRE-CONTINUATION-20261025T080000Z/` محفوظ است. manifest نهایی کل سورس، تست و شواهد TF-03 را فهرست می‌کند.
