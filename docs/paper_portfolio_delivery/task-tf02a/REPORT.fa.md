# گزارش تحویل TF-02A — بستن پنج نقص بازبینی رابط تقویم

تاریخ: 2026-10-24 (تاریخ برنامه). نتیجه: **PASS برای هر پنج گروه؛ TF-02 با این اصلاحات بسته شد. TF-03 شروع نشده است.**

مبنای این مأموریت، بازبینی مستقل TF-02 (`docs/paper_portfolio_delivery/task-tf02/review/`) بود که ۱۱۱ آزمون تحویل را پاس کرده و با fixtureهای جداگانه پنج دسته نقص یافته بود. هر پنج یافته ابتدا به regression مستقل تبدیل شد و سپس در adapter و اتصال مصرف‌کنندگان اصلاح شد؛ probe و گزارش تاریخی بازبینی بازنویسی نشد. درخواست توکن لازم نبود و هیچ درخواست شبکه‌ای انجام نشد؛ حساب جاری، قواعد pinشدهٔ 1.2.0، قراردادها و O00 فقط خوانده/hash شدند و همهٔ مسیرهای ACCOUNT/RULES/RUN/OUT/PUBLIC در آزمون‌ها و evidence به temp هدایت شدند.

## فرمان آزمون و شمارش واقعی

```powershell
& .venv/Scripts/python.exe -X utf8 -m pytest ranking_research/tests/test_public_market_calendar.py ranking_research/tests/test_paper_calendar_interface.py ranking_research/tests/test_paper_account_atomic.py ranking_research/tests/test_paper_cycle_http.py ranking_research/tests/test_paper_calendar_tf02a_regressions.py -q --basetemp D:/RFA/Company-Financial/.pytest_tmp_tf02a
```

خروجی واقعی: **149 passed in 364.79s** — تفکیک: 34 (collector) + 18 (interface) + 56 (atomic) + 3 (cycle http) + **38 (regressionهای جدید TF-02A)**. مجموعهٔ ۱۱۱تایی بازبینی بدون حذف، پاس شد؛ تنها تغییر در فایل تست رابط، اصلاح پیش‌شرط fixtureها بود (بند «تغییر fixtureها»).

فایل regression جدید: `ranking_research/tests/test_paper_calendar_tf02a_regressions.py` (۳۸ آزمون، کاملاً offline، همهٔ خروجی‌ها در temp).

## یافتهٔ ۱ — دو تاریخ ناسازگار در manifest، خرید را به جلسهٔ بعد منتقل می‌کرد (P1)

**رفتار معیوب:** سطح بالای manifest با روز تصمیم کنترل می‌شد ولی ارزیابی از `policy.window_start` داخلی استفاده می‌کرد؛ تغییر فقط پنجرهٔ داخلی به 20260902 با hash تازه و صحیح، آماده=true با first=20260905 و count=1 می‌داد و entrypoint با قیمت همان روز نادرست FILL_APPLIED می‌شد (شواهد بازبینی: `nested_window_mismatch`، `wrong_day_actual_fill`).

**محل اصلاح** — `ranking_research/paper_calendar.py` در `resolve_public_calendar`:
- **یک مبنای روز تهران**: `decision_local_date` و `decision_at_utc` باید یک روز تهران‌ای باشند؛ تفاوت → `DECISION_DATE_TIME_INCONSISTENT` (با `tehran_local_date` خود collector؛ منطق موازی ساخته نشد).
- **پنجره روی هر سه محل ثبت**: `manifest.window_start` و `policy.window_start` و روز تصمیم باید یک مقدار باشند؛ تخلف → `CALENDAR_WINDOW_MISMATCH` با ذکر هر سه مقدار. hash صحیح فقط ثبات فایل را اثبات می‌کند نه سازگاری معنایی آن را.
- **فیلدهای تکراریِ مؤثر بر ارزیابی**: `market_scope`، `policy_version` (سطح بالا در برابر داخلی) و `policy.indices` (باید دقیقاً پروفایل‌های ثبت‌شدهٔ TSE باشند) یک تفسیر اجازه می‌دهند؛ تخلف → `CALENDAR_MANIFEST_INTERNAL_INCONSISTENT`. تفاوت نام‌گذاری «سیاست collector» و «سیاست مصرف‌کننده» حفظ شد و هیچ برابری رشته‌ای بین دو قرارداد متفاوت تحمیل نشد.
- همهٔ این ردّها structural و پیش از هر تغییر حساب‌اند؛ ارزیابی همچنان از raw معتبر بازمحاسبه می‌شود.

**آزمون‌ها/شواهد:** `test_g1_control_two_session_package_first_and_count` (کنترل سالم: تصمیم 20260901، جلسات 20260902 و 20260905، first=20260902، count=2)، `test_g1_window_disagreement_refused_before_any_account_change` (پارامتری inner/outer؛ اجرای واقعی `apply.main` با قیمت 20260905: رد `CALENDAR_WINDOW_MISMATCH`، بدون fill/debit/event/receipt و bytes ثابت)، `test_g1_duplicated_field_disagreement_refused`، `test_g1_decision_datetime_must_describe_the_same_teheran_day` (مرز دقیق نیمه‌شب تهران 20:30Z: یک ثانیه قبل رد، روی مرز پذیرش، past-midnight رد). شاهد واقعی entrypoint: `evidence.json` بخش `refusals.inner_window_mismatch_wrong_day_price` (bytes_unchanged=true).

## یافتهٔ ۲ — مسیر NSCStart ترتیب روز را اشتباه می‌گرفت و readiness را دور می‌زد (P1)

**رفتار معیوب:** جلسات تکمیل‌شده به ترتیب ردیف ورودی مصرف می‌شدند (برگرداندن ترتیب، first را از 20261023 به 20261024 می‌برد) و دروازهٔ `calendar_ready` فقط در شاخهٔ عمومی اعمال می‌شد؛ manifest دریافت‌شده پیش از تصمیم در adapter بلوکه می‌شد ولی entrypoint خرید می‌زد (شواهد: `nsc_reversed_rows`، `nsc_predating_source_actual_fill`).

**محل اصلاح:**
- `paper_calendar.resolve_nscstart_calendar`: جلسات مشتق‌شده (`completed` و `dates`) مرتب‌شده صعودی مصرف می‌شوند؛ first/latest/count دیگر به ترتیب ردیف ورودی وابسته نیستند. قرارداد ۲۰جلسه‌ای، کنترل hash/raw و تطبیق manifest دست‌نخورده ماند.
- `apply_paper_fill.run_locked`: دروازهٔ مشترک `CALENDAR_NOT_READY;<reasons>` پس از resolve هر دو provider اعمال می‌شود — پیش از fill، انقضا، ثبت observation و هر نوشتن. مسیر observation (`--observe-order-state`) جدا از fill ماند و بدون گزینهٔ صریح هیچ داده‌ای نمی‌نویسد؛ با تقویم نامزد، خود observation هم تا رفع انسداد بسته است و علت واقعی انسداد (`SOURCE_RETRIEVED_BEFORE_DECISION` و…) عیناً حفظ می‌شود.

**آزمون‌ها/شواهد:** `test_g2_nscstart_first_latest_count_ignore_row_order` (صعودی/نزولی/درهم‌ریخته → first=20261023، count=2، coverage یکسان)، `test_g2_predating_nscstart_manifest_blocks_the_fill_entrypoint` (adapter: ready=false با علت؛ entrypoint: رد `CALENDAR_NOT_READY;SOURCE_RETRIEVED_BEFORE_DECISION` با bytes ثابت)، `test_g2_healthy_nscstart_fixture_still_buys_from_the_entrypoint` (fixture سالم NSCStart از entrypoint واقعی خرید می‌کند تا بستن بی‌قیدوشرط این مسیر جای رفع نقص را نگیرد). شاهد واقعی: `evidence.json` بخش `nscstart_predating_manifest` (bytes_unchanged=true).

## یافتهٔ ۳ — cross-check pinشده در مصرف دوباره خوانده و اعتبارسنجی نمی‌شد (P1)

**رفتار معیوب:** adapter پنج منبع اصلی را بازسازی می‌کرد ولی مجموعهٔ cross-check سهام را به ارزیابی برنمی‌گرداند؛ خراب‌کردن raw آرشیو اعلام‌شده بدون تغییر hash آن، ready=true با CORROBORATED_PUBLIC می‌داد و نبود trade_status نامزد گزارش وضعیت را به evidence_gap می‌برد (شاهد: `corrupted_pinned_cross_check_raw`).

**محل اصلاح** — `resolve_public_calendar`: اگر manifest بخش `stock_cross_check` را اعلام کرده باشد، همان انتخاب با منطق بازپخش خود collector (`tf._replay_stock_cross`: همان سقفِ ثبت‌شده — صفر صفر می‌ماند —، همان identity map و کنترل hashهای snapshot و rawها) بازسازی می‌شود؛ خطای بازپخش → `STOCK_CROSS_REPLAY_FAILED`. مجموعهٔ بازسازی‌شده وارد `evaluate_public_calendar` می‌شود (کیفیت و conflict و شاهد معاملهٔ نامزد) و در پاسخ با `stock_cross_check.rebuilt_from_pinned_raw` خلاصه می‌شود. by_symbol ذخیره‌شده به‌تنهایی شاهد نیست. **نبود** cross-check (اجرای collector با `--no-cross-check`) وضعیتی مجاز و متفاوت است و با «اعلام‌شده ولی خراب» یکی نمی‌شود. refresh نیازی به تغییر منطق نداشت: شاهد نامزدش (`answer["evaluation"]["stock_cross_check"]["by_symbol"]`) اکنون دادهٔ واقعی بازسازی‌شده می‌گیرد؛ آرشیو کوتاه‌تر همچنان `evidence_gap_archive_ends_before_target_day` است، نه توقف قطعی یا ادعای تعطیلی.

**آزمون‌ها/شواهد:** `test_g3_broken_pinned_cross_inputs_refused_at_consumption` (چهار خرابی: raw دستکاری‌شده، raw گمشده، snapshot manifest تغییرکرده، مجموعهٔ منتخب تغییرکرده — همگی `STOCK_CROSS_REPLAY_FAILED`؛ مورد raw دستکاری از `apply.main` نیز با حساب byte-identical رد می‌شود)، `test_g3_rebuilt_conflict_closes_readiness` (معاملهٔ واقعی سهام در روزِ خارج از تقویم → `CALENDAR_QUALITY_CONFLICT`، ready=false)، `test_g3_empty_one_and_limited_selections_still_consume` (سقف 0/1/نامحدود سالم)، `test_g3_refresh_consumes_candidate_witness_and_short_archive_is_gap` (refresh.main: آرشیو پوشاننده → `candidate_data_covers_target_day` با archive_end=20260905؛ آرشیو کوتاه → `evidence_gap_archive_ends_before_target_day`). شاهد واقعی: `evidence.json` بخش `refusals.corrupted_pinned_cross_raw` (`STOCK_CROSS_REPLAY_FAILED; REPLAY_RAW_CHANGED`، bytes_unchanged=true).

## یافتهٔ ۴ — replay روز بعد با شرط تازگی امروز رد می‌شد (P2)

**رفتار معیوب:** receipt ساعت معتبر اجرای اولیه را ثبت نمی‌کرد؛ تکرار همان ورودی با ساعت روز بعد `CALENDAR_NOT_READY;FRESHNESS_SOURCE_STALE` می‌داد (شاهد: `public_replay_next_day`). تستی که ساعت اولیه را دوباره به helper می‌داد، replay عملیاتی را اثبات نمی‌کرد.

**محل اصلاح** — `apply_paper_fill` (شاخهٔ عمومی):
- receipt نسخهٔ 2 دو فیلد افزودنی می‌گیرد: `calendar.validated_at_utc` (ساعت اعتبارسنجی همان اجرا، به‌همان عملیات atomic حساب) و `calendar.evidence_manifest_sha256`. **نسخهٔ receipt افزایش نیافت**؛ نبود `validated_at_utc` خود نشانگر receipt قدیمی است و «غیرقابل‌اثبات» گزارش می‌شود، نه ساختن زمان: رد صریح `FILL_REPLAY_VALIDATION_CLOCK_UNPROVABLE`.
- برای replay دقیق، پیش از هر استفاده از ساعت گذشته، هویت همان اجرا (account_id/decision_id/order_id) و برابری ورودی‌های pinشده (manifest sha، policy sha، evidence sha) با receipt احراز می‌شود؛ تخلف → `FILL_REPLAY_INPUTS_CHANGED` و receipt قبلی هرگز بازنویسی نمی‌شود. سپس ساعت اعتبارسنجی از receipt بازیابی و جای ساعت امروز/ساعت دستی می‌نشیند؛ تازگی همان شواهد در ساعت ثبت‌شدهٔ خودش اعتبارسنجی می‌شود. پرچم exact-replay به‌تنهایی هیچ گذرنامه‌ای از تازگی نیست.
- اجرای جدید (بدون receipt) همیشه با ساعت امروز ارزیابی می‌شود: شواهد کهنه رد (`test_g4_fresh_account...`). قواعد legacy مسیر NSCStart بدون دلیل تغییر نکرد (بدون سقف عمر منبع؛ فقط «دریافت پس از تصمیم» که ساعت‌مستقل است).

**آزمون‌ها/شواهد:** `test_g4_next_day_replay_succeeds_via_recorded_clock` (apply سالم → retry همان ورودی با ساعت روز بعد، بدون تزریق ساعت قبلی → `FILL_ALREADY_APPLIED` با `replayed_at_recorded_validation_clock`؛ یک debit/fill/event/receipt و bytes بدون تغییر؛ همین رفتار پس از mark)، `test_g4_replay_refuses_changed_inputs_or_unprovable_clock` (hash متفاوت، policy متفاوت، evidence متفاوت، receipt فاقد clock — هرکدام با کد خودش رد و bytes ثابت)، `test_g4_crash_harness_atomicity_and_clock_rules` با harness خرابی موجود: قطع پیش از replace (exit 75) → فایل در حالت معتبرِ قبل؛ retry صادقانهٔ روز بعد **رد** می‌شود (خرید تازه با ساعت گذشتهٔ ساختگی مجاز نیست)؛ قطع پس از replace (exit 74) → دقیقاً یک fill ثبت؛ retry پس از commit دوباره هزینه کسر نمی‌کند. شاهد واقعی: `evidence.json` بخشهای `public_fill_then_next_day_replay` (ساعت ثبت‌شده 2026-10-23T12:05:00+00:00 و بازیابی همان در replay؛ bytes ثابت) و `crash_harness`.

## یافتهٔ ۵ — اتصال سیاست کامل و بین مصرف‌کنندگان یکسان نبود (P1)

**رفتار معیوب:** کنترل binding سفارش مشروط به وجود آن بود و binding سطح حساب اصلاً بررسی نمی‌شد؛ حساب با binding نادرست حساب و binding حذف‌شدهٔ سفارش FILL_APPLIED می‌گرفت (شاهد: `missing_order_and_wrong_account_binding`). cycle فقط شناسهٔ سیاست تصمیم را کنترل می‌کرد و refresh اعتبارسنجی مشترک نداشت.

**محل اصلاح:**
- تابع مشترک `paper_calendar.check_public_policy_binding(account, rules_doc, policy, policy_sha256)`: binding در **چهار سطح** account/decision/order/rules الزامی و سازگار است؛ **نبود binding هیچ سطحی خودش mismatch است** و شرط را حذف نمی‌کند؛ id و sha256 (و در صورت ثبت، version/provider) باید با سیاست pinشده برابر باشند. حساب legacy بدون binding تحت قواعد خودش خواندنی می‌ماند و انتخاب پروفایل عمومی برایش هرگز مهاجرت خودکار نیست — فقط رد با علت روشن (`CALENDAR_POLICY_MISMATCH; … level …`).
- این کنترل واحد در **apply** (جایگزین کنترل درون‌خطی)، **refresh** (آرگومان `--execution-rules`؛ نتیجه در `public_calendar.account_compatibility` جدا از کیفیت داده گزارش و در barriers با وضعیت `account_profile_mismatch` نمایش داده می‌شود — حساب ناسازگار هرگز no_new_session/ready=true به‌عنوان آمادگی حساب نمی‌گیرد) و **cycle** (پارامتر `rules_path` در `acquire_order_calendar`؛ نتیجه در `profile_mismatch_detail`) مصرف می‌شود. محدودیت PIT فروش و تقویم رسمی دست‌نخورده ماند.
- خروجی `apply` فیلد `sessions_after_decision` گرفت تا first/count سه مصرف‌کننده مستقیماً قابل مقایسه باشد.

**آزمون‌ها/شواهد:** `test_g5_binding_is_mandatory_and_consistent_at_every_level` (۱۱ حالت: حذف/شناسهٔ نادرست/hash نادرست در هر سطح + ترکیب دقیق بازبینی «حساب نادرست + سفارش بدون binding» — همگی `CALENDAR_POLICY_MISMATCH` با نام سطح در پیام و bytes ثابت؛ کنترل سالم همان پکیج خرید می‌کند)، `test_g5_one_input_consistent_across_fill_status_and_cycle` (یک ورودی واحد از هر سه entrypoint واقعی: سالم → first=20260902/count=2 در هر سه؛ نسخهٔ نامعتبر completion → هر سه با همان علت `COMPLETION_ASSUMPTION_UNAVAILABLE` بسته، نه سه روایت متفاوت)، `test_g5_cycle_with_fake_acquisition_outcomes` (acquisition جعلی موفق با اشاره‌گر hash ناسازگار → `blocked_public_manifest_hash_mismatch`؛ بدون اشاره‌گر → `blocked_public_manifest_missing`؛ هیچ glob/mtime جایگزین نمی‌کند — شکست در `test_cycle_public_acquisition_never_falls_back_to_old_manifest` قبلی نیز پوشش دارد)، `test_g5_real_account_copy_reports_mismatch_in_refresh_and_keeps_ledger` (کپی موقت حساب جاری + manifest عمومی: refresh وضعیت `account_profile_mismatch` می‌دهد، کیفیت داده جداگانه، فایلهای اصلی فقط hash شدند). هیچ چرخهٔ واقعی تولید اجرا نشد.

## تغییر fixtureها (اصلاح پیش‌شرط، نه تغییر انتظار)

- `_public_account_fixture` (تست رابط)Binding سطح حساب (`account.calendar_policy`) به پیش‌شرط‌های fixture افزوده شد؛ کنترل سالم (`test_g1_control...` و کنترل خرید در `test_g5_binding...`) نشان می‌دهد fixture سالم همچنان موفق است و تنها تغییر مورد آزمون باعث رد می‌شود.
- فراخوانی refresh در تست، `--execution-rules` pinشدهٔ fixture می‌گیرد؛ فراخوانیهای cycle پارامتر `rules_path` می‌گیرند (پیش‌فرض همان مسیر pinشدهٔ واقعی است).
- انتظار هیچ تست موجودی با «رفتار فعلی» عوض نشد؛ ۱۱۱ آزمون قبلی پاس ماندند.

## Evidenceهای واقعی

- `evidence/evidence.20261024T175135733088Z.json` — خروجی واقعی entrypointها (subprocess واقعی با الگوی redirect ثابت‌های ماژول، همان harness تستهای atomic): apply و replay روز بعد با ساعت بازیابی‌شده، پنج رد با hash حساب قبل/بعد (همه byte-identical)، harness خرابی (75/74)، refresh روی کپی حساب جاری، و hash شش فایل محافظت‌شده.
- `evidence/generate_evidence.py` — تولیدکنندهٔ همان evidenceها؛ قابل اجرای مجدد، offline، فقط temp.

## فایلهای محافظت‌شده (قبل == بعد)

هر شش فایل ثبت‌شده در تحویل TF-02 دوباره hash و مطابقت داده شدند (رکورد کامل در evidence): `client/public/research/v12-36/paper-portfolio.json`، `execution_rules_v1_2_0.json`، سه `analysis/future_evaluation contract locked` و `o00_session_calendar.csv` — همگی MATCH. دفتر رسمی دست‌نخورده است؛ هیچ commitی از سوی من انجام نشد.

## محدودیت‌ها و موارد باز

- سیاست `public-paper-v1` همچنان پیشنهاد آزمایشی است و روی حساب جاری فعال نشده؛ مهاجرت/فعال‌سازی TF-03 است.
- کیفیت CORROBORATED_PUBLIC هرگز گواه رسمی کامل‌بودن تقویم نیست؛ پایان جلسه بر پایهٔ فرض ثبت‌شده با همان برچسب نمایشی در خروجیها می‌ماند.
- `validated_at_utc` فقط در receiptهای عمومیِ جدید ثبت می‌شود؛ receiptهای قدیمی فاقد آن، صریحاً «غیرقابل‌اثبات» رد می‌شوند و زمان ساخته نمی‌شود.
- آزمون‌ها و evidenceها کاملاً offlineاند؛ اجرای زندهٔ جدیدی در این مأموریت انجام نشد (شواهد اجرای زندهٔ TF-02 معتبر و hand-hash می‌مانند).

## توقف

مطابق قرارداد، پس از تحویل برای بازبینی متوقف می‌شوم. اجرای عملیاتی روی حساب آزمایشی، فعال‌سازی و مهاجرت حساب جاری (TF-03) خارج از این مأموریت است و فقط با تصمیم صریح شما آغاز می‌شود.
