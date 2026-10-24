# تحویل TF-02 — رابط تقویم مشترک و اتصال آزمایشی مسیر بدون توکن

تاریخ: 2026-10-24. محدوده: فقط رابط/اتصال آزمایشی؛ حساب جاری، قواعد pinشده، قرارداد قفل‌شده و دفتر رسمی تغییر نکردند. فعال‌سازی و مهاجرت حساب، TF-03 است.

## خلاصه

- **رابط مشترک** `ranking_research/paper_calendar.py` ساخته شد: پین‌کردن manifest + hash، بازمحاسبهٔ کامل ارزیابی از raw (فیلدهای کیفیت/جلسهٔ ذخیره‌شده هرگز حقیقت تلقی نمی‌شوند)، دروازهٔ تازگی نسخه‌دار، پاسخ یکسان به همهٔ مصرف‌کنندگان. هر دو provider (`nscstart` و `public`) از همین توابع عبور می‌کنند؛ NSCStart ساختگی یا تبدیل منبع عمومی به Data/NSCEnd جعلی وجود ندارد.
- **سیاست نسخه‌دار `public-paper-v1`** در `ranking_research/paper_calendar_policy.public-paper-v1.json`: پیشنهاد قابل‌آزمون برای حساب کاغذی آزمایشی؛ وضعیت `proposed-experimental`، فعال نشده. پذیرش فرض پایان جلسه فقط در policy consumer است؛ خروجی collector همچنان `completion_officially_confirmed=false` می‌ماند.
- **هر چهار مصرف‌کننده متصل شدند** با حفظ کامل guardهای قبلی: `apply_paper_fill.py`، `refresh_paper_decision_status.py`، `paper_cycle.py`، `build_codal_factor_inputs.py`.
- **سه شرط بازبینی TF-01A بسته شد** (گام اول). **۱۱۱ آزمون سبز** است (۳۴ تقویم + ۱۸ رابط + ۵۹ مبنا). عدد صحیح مبنای TF-01A **۸۹** بود (۳۰+۵۹)؛ همان پایه اکنون با ۴ آزمون گام اول و ۱۸ آزمون رابط به ۱۱۱ رسیده است.
- **smoke عمومی واقعی بدون توکن** اجرا شد (۵ GET عمومی، بدون هیچ درخواست احراز هویت‌شده): `CORROBORATED_PUBLIC`، آخرین جلسهٔ مشاهده‌شده همچنان **20261021** (سابقهٔ منجمد به جلسهٔ شنبه تبدیل نشد)، `NO_NEW_SESSION` با شمارش ۰، بدون conflict، cross-check با ۱ نماد واجد و ۲۵۳ skip.
- **dry-run حساب واقعی با قواعد قدیمی و manifest عمومی** → `CALENDAR_POLICY_MISMATCH` با کپی موقت؛ فایل اصلی فقط hash/read شد و hash آن تغییر نکرد.

## گام اول — بستن سه شرط بازبینی TF-01A

1. **حفظ دقیق مجموعهٔ cross-check در بازپخش** — `_replay_stock_cross` اکنون `max_symbols` را همان‌طور که pin شده بازپخش می‌کند (صفر صفر می‌ماند و هرگز معنی «بی‌محدودیت» نمی‌گیرد) و مجموعهٔ واجدین بازپخش باید **دقیقاً برابر** مجموعهٔ pinشده باشد؛ حذف یا اضافهٔ بی‌صدا خطای `REPLAY_ELIGIBLE_SET_CHANGED` می‌دهد (با فهرست missing/added). هویت شاهد اکنون به insCode هم گره خورده است: عنوان بازار در identity_map بدون تطبیق insCode رکورد، `identity_ins_code_mismatch` است و واجد نمی‌شود. آزمون‌ها: `test_replay_preserves_cross_check_selection_exactly` (چهار حالت: محدود مثبت چندعضوی، صفر، مجموعهٔ خالی بدون حد ثبت‌شده، رشد بی‌صدای مجموعه) و `test_identity_evidence_must_bind_to_the_record_ins_code`.
2. **ساعت متفاوت = بازارزیابی برچسب‌دار** — با `--reference-now-utc` متفاوت از ساعت pinشده، خروجی `mode=re-evaluated` است (نه replay) با `reference_clock_changed=true` و `reevaluation_reasons`؛ timestampهای دریافت منابع در هر دو حالت pin می‌مانند. ساعت pinشدهٔ همان → همچنان `replay`. آزمون: `test_replay_clock_override_is_reevaluated_not_replay`.
3. **دروازهٔ تازگی در مرز مصرف** — `check_freshness` در adapter: حداکثر فاصلهٔ دریافت تا زمان ارزیابی **۶ ساعت**، timestamp نامعتبر/بدون UTC مردود، دریافتِ آینده بیش از **۵ دقیقه** مردود (`SOURCE_RETRIEVED_IN_FUTURE`)، دریافت پیش از تصمیم مردود (`SOURCE_RETRIEVED_BEFORE_DECISION`). این اعداد «فرض عملیاتی نسخه‌دار» (`public-paper-freshness@1`) در فایل سیاست‌اند، نه قانون بورس. چون دروازه در **ساعت تزریق‌شده** سنجیده می‌شود، بازپخش تاریخی یک receipt قدیمی با ساعت ثبت‌شدهٔ همان اجرا مجاز می‌ماند و همان rawها برای مصرف امروز stale است. آزمون‌ها: `test_weekend_fresh_vs_stale_evidence_boundary`، `test_broken_public_inputs_stop_without_account_changes[predates_decision|future_ts]`.
4. دو اصلاح کم‌هزینه: اختلاف روزهای پیش از پنجرهٔ تصمیم وقتی هر دو شاخص فعال بوده‌اند اکنون `overlapping_range_date_difference` نام می‌گیرد و از `history_start_difference` جدا است (`test_pre_window_differences_split_start_vs_overlapping_range`)؛ و عدد ۸۹ مبنای TF-01A در همین گزارش ثبت شد. گزارش‌های تاریخی قبلی بازنویسی نشدند.

## گام دوم — قرارداد رابط مشترک

`resolve_calendar(provider=…, manifest_path, decision_local_date, decision_at_utc, now_utc, consumption_mode, …)` — انتخاب provider همیشه ورودی صریح است؛ نه global env و نه «آخرین فایل موجود». حالت‌های مصرف: `live-preview` / `fixture-apply` / `exact-replay`.

خروجی دست‌کم شامل: `interface_version`، `policy{id,version,sha256,status}`، `manifest{path,sha256,run_id,mode,reference_now_utc}`، `identities`، `market_scope`، `quality` (+`quality_recomputed_from_raw: true`)، `conflicts`، `freshness{state,rules,sources,problems}`، `coverage`، `completion{type,value,officially_confirmed,tails_aligned_with_assumption,…}`، `sessions_after_decision{state,count,first_session,count_is_unknown}`، `first_usable_session`، `eligible_session_count`، `readiness{calendar_ready,for_consumption,blocking_reasons}`، `capabilities`، `display_label_fa`.

تفکیک سه مفهوم حفظ شد: کیفیت مشاهده (`quality`) ≠ نوع تکمیل (رسمی / **فرض عملیاتی نام‌دار** / نامعلوم) ≠ آمادگی تقویم برای یک مصرف مشخص. `readiness.note` صریح می‌گوید آمادگی تقویم مجوز کامل معامله نیست؛ قیمت، تغییر سرمایه، حساب و receipt همچنان در مصرف‌کننده کنترل می‌شوند.

رد شدن‌های ساختاری (استثنا با کد دقیق): hash نامعتبر manifest (`CALENDAR_MANIFEST_HASH_MISMATCH`)، key تکراری منبع (`CALENDAR_MANIFEST_DUPLICATE_SOURCE_KEY`)، کلیدهای ناقص (`CALENDAR_MANIFEST_SOURCE_KEYS_INVALID`)، provider/dataset/parser نامرتبط (`CALENDAR_POLICY_PROVIDER_MISMATCH`، `CALENDAR_PARSER_VERSION_MISMATCH`، …)، window ≠ روز تصمیم (`CALENDAR_WINDOW_MISMATCH`)، نامزد ناهمخوان (`CALENDAR_CANDIDATE_MISMATCH`)، URL ناسازگار (`CALENDAR_SOURCE_URL_INCONSISTENT`)، ناسازگاری کیفیت ذخیره‌شده با بازمحاسبه (`CALENDAR_MANIFEST_QUALITY_INCONSISTENT`). نقص‌های کیفیت (CONFLICT، INSUFFICIENT_COVERAGE، COMPLETION_*) به‌جای crash در `readiness.blocking_reasons` با نام دقیق پاسخ می‌شوند — پاسخ یکسان با علت انسداد.

### مسیر NSCStart از همان رابط

`resolve_nscstart_calendar` همان اعتبارسنجی قبلی مسیر قفل‌شده را انجام می‌دهد (منبع `TSETMC documented API MarketInfo/NSCStart`، hash خام، تطبیق sessions با raw، پنجرهٔ دقیقاً ۲۰جلسه‌ای پوشانندهٔ روز تصمیم، `NO_COMPLETED_OFFICIAL_SESSION_AFTER_DECISION`) با همان کدهای خطای تاریخی، و فقط یک timestamp معتبر UTC و عدم تقدم از تصمیم می‌خواهد (بدون سقف کهنگی — دقیقاً رفتار فعلی). آزمون: `test_nscstart_contract_via_adapter_unchanged` (شامل رد پنجرهٔ ۱۹تایی). رابط منبع عمومی را به NSCStart جعلی تبدیل نمی‌کند و پذیرش یک منبع در adapter به معنی قابل‌قبول‌شدن آن برای همهٔ قراردادها نیست.

## گام سوم — سیاست `public-paper-v1`

شرایط لازم برای آمادگی مصرف: `quality == CORROBORATED_PUBLIC`، هر پنج منبع سالم، anchor تصمیم برای هر شاخص، تطبیق بازار/نوع نامزد، نبود conflict، تازگی، و **تکمیل با فرض نام‌دار**: توافق اجزای LastPossibleDeven **و** هم‌خوانی انتهای هر دو تاریخچه با همان مقدار (`tails_aligned_with_assumption`)؛ نبود فرض، اختلاف اجزا، watermark عقب‌مانده یا tail ناهم‌خوان آمادگی را می‌بندد (`COMPLETION_ASSUMPTION_UNAVAILABLE`، `COMPLETION_TAIL_MISALIGNED`).

اقتصاد سفارش تغییر نکرد: تعداد صحیح سهم، ریال→تومان تقسیم بر ۱۰ با ROUND_HALF_UP، هزینه ۰٫۵٪، نخستین جلسهٔ پذیرفته‌شدهٔ بعد از **تاریخ محلی** تصمیم، عدم جایگزینی قیمت جلسهٔ بعد، انقضای ۳ جلسهٔ پذیرفته‌شدهٔ همین پروفایل. روزِ بدون ردیف «تعطیل قطعی» نیست و تاریخ مشترک ممکن است در همهٔ منابع جا افتاده باشد — این محدودیت صریح مانده است.

اتصال سیاست: حساب/تصمیم/سفارش آزمایشی باید `calendar_policy{id,sha256}` برابر با نسخهٔ درخواستی داشته باشند و فایل قواعد هم همین binding را دارد؛ سفارش قدیمی با rules hash قبلی و manifest عمومی → `CALENDAR_POLICY_MISMATCH` بدون تغییر بایت‌های حساب (آزمون‌های `policy` و `real_account_dry_run_mismatch_on_temp_copy`). برچسب نمایش «سبد کاغذی با تقویم عمومی؛ پایان جلسه بر پایهٔ فرض ثبت‌شده، بدون گواه کامل‌بودن تقویم» در خروجی preview، receipt (نسخهٔ ۲ با فیلد `calendar`) و event log می‌آید، نه فقط log توسعه‌دهنده. `completion_officially_confirmed=false` در خروجی collector دست‌نخورده است؛ وضعیت والد فقط در دامنهٔ interface/preview اعلام می‌شود.

## گام چهارم — مصرف‌کنندگان متصل

| مصرف‌کننده | اتصال | نکتهٔ کلیدی |
|---|---|---|
| `apply_paper_fill.py` | `--calendar-provider public` با policy/manifest pinشده | همهٔ guardهای قیمت همان جلسه/حجم/هویت/corporate action/cash/receipt حفظ شد؛ apply واقعی fixture از همین entrypoint؛ preview و دادهٔ ردشده byte-identical؛ receipt v2 با policy و manifest pinشده؛ replay همان receipt پس از mark دوباره بدهکار نمی‌شود؛ `SESSION_NOT_CONFIRMED_BY_PUBLIC_COMPLETION_ASSUMPTION` جایگزین گیت NSCStart-خاص در پروفایل عمومی؛ «دریافت موفق بدون جلسهٔ جدید» خروجی موفقِ انجام‌نشده است |
| `refresh_paper_decision_status.py` | `--calendar-provider public` + manifest/sha | همان first-session/count از رابط؛ «صفر جلسهٔ مشاهده‌شده» ≠ «شمارش نامعلوم» (`count_is_unknown`)؛ گزارش نبود معاملهٔ نامزد فقط با پوشش همان روز؛ آرشیو کوتاه‌تر → `evidence_gap_*` نه توقف/بدون‌معامله؛ خروجی‌ها با `--output-dir/--public-output-dir` به temp هدایت می‌شوند |
| `paper_cycle.py` | `--calendar-provider` (nscstart پیش‌فرض، public اختیاری) | مسیر عمومی به token مشروط نیست و نبود token blocker تقویم نیست؛ manifest فقط از همان run (`latest-manifest.json` همان پوشه + کنترل hash) — بازگشت به manifest قدیمی با glob/mtime ممنوع (`*_no_fallback`)؛ profile سفارش از binding حساب کنترل می‌شود (`blocked_calendar_profile_mismatch`)؛ بدون نشست جدید: acquisition موفق، اجرای سفارش انجام‌نشده |
| `build_codal_factor_inputs.py` | `--sales-timing-calendar-provider public` → `SALES_PIT_TIMING_CAPABILITY_NOT_GRANTED_PUBLIC_PROFILE` | مانع admission فروش/tقویم رسمی آینده با دلیل خودش گزارش می‌شود، نه «توکن نداریم» و نه موفقیت ساختگی؛ profile عمومی به‌صورت پیش‌فرض مجوز sales PIT نمی‌دهد |

## آزمون‌ها و شواهد واقعی

فرمان کامل (همه سبز):

```
.venv/Scripts/python.exe -X utf8 -m pytest \
  ranking_research/tests/test_public_market_calendar.py \
  ranking_research/tests/test_paper_calendar_interface.py \
  ranking_research/tests/test_paper_account_atomic.py \
  ranking_research/tests/test_paper_cycle_http.py -q
# 111 passed in 174.38s   (34 + 18 + 59)
```

پوشش ۹ مسیر پذیرش مأموریت در `ranking_research/tests/test_paper_calendar_interface.py`: (1) مسیر عمومی بدون token و بدون هیچ NSCStart؛ (2) preview بدون تغییر بایت → apply با یک debit/fill/event/receipt → replay semantically-identical؛ (3) raw خراب / hash متفاوت / key تکراری / policy نامرتبط / دریافت قبل از تصمیم / timestamp آینده → توقف بدون تغییر حساب؛ (4) آخرهفتهٔ تازه → جلسهٔ پذیرفته‌شده؛ همان فایل قدیمی → `SOURCE_STALE`؛ replay تاریخی با ساعت خودش مجاز؛ (5) بازار باز بدون bar نامزد → جلسه حفظ می‌شود، آرشیو کوتاه → evidence gap؛ (6) اختلاف دو شاخص / نبود anchor / اختلاف watermark / tail ناهم‌خوان → کد اختصاصی؛ (7) انقضای ۳ جلسه‌ای پذیرفته‌شده (`EXPIRED_NO_FILL` بدون بدهکار) و مرز روز تهران؛ (8) یک پاسخ واحد برای fill/status/cycle (شامل `blocked_calendar_profile_mismatch`)؛ (9) حساب واقعی + قواعد قدیمی + manifest عمومی → `CALENDAR_POLICY_MISMATCH` روی کپی، فایل اصلی فقط hash شد.

### smoke عمومی واقعی (بدون توکن، 2026-10-24T12:39:55Z)

```
.venv/Scripts/python.exe -X utf8 ranking_research/future_eval_v12_30/acquire_public_market_calendar.py \
  --window-start 20261022 --output-dir ranking_research/output/public_market_calendar_tf02
```

نتیجهٔ واقعی: HTTP 200 از هر پنج endpoint عمومی (cdn.tsetmc.com ×4 + service.tsetmc.com ×1؛ بدون Authorization، بدون api.tsetmc.com)؛ `quality=CORROBORATED_PUBLIC`، `readiness=USABLE_COMPLETION_UNVERIFIED`، `assumed_completion=20261021`، `sessions_after_decision=NO_NEW_SESSION (0)`، conflicts=0، cross-check: 254 رکورد → eligible=1، skipped=253، offline replay داخلی همهٔ فیلدها برابر. manifest: `ranking_research/output/public_market_calendar_tf02/manifest.20261024T123955774571Z.json` (sha256 `ee23813fe7510239681c66ded86220093921adf2d463149880e6b64ffb0f3301`). سابقهٔ واقعی هنوز آخرین جلسهٔ 20261021 است — به جلسهٔ شنبه تبدیل نشد و نبود دادهٔ جدید مجوز جعل جلسه یا fill نیست.

### بازپخش pinشده از همان manifest (آفلاین، بدون حساب)

`mode=replay` با حساب/snapshot پیش‌فرض ناموجود، `field_equality` همه true — شواهد: `evidence/replay.stdout.json`.

## فرمان قابل‌اجرا برای preview (ورودی pinشده، خروجی موقت)

```powershell
# از ریشهٔ مخزن؛ فقط خواندنی برای حساب جاری؛ همهٔ خروجی‌ها در پوشهٔ موقت
$d = Join-Path $env:TEMP ("tf02-preview-" + [guid]::NewGuid().ToString("N").Substring(0,8))
.venv\Scripts\python.exe -X utf8 ranking_research\future_eval_v12_30\refresh_paper_decision_status.py `
  --calendar-provider public `
  --public-calendar-manifest ranking_research\output\public_market_calendar_tf02\manifest.20261024T123955774571Z.json `
  --public-calendar-manifest-sha256 ee23813fe7510239681c66ded86220093921adf2d463149880e6b64ffb0f3301 `
  --reference-now-utc 2026-10-24T13:00:00+00:00 `
  --output-dir "$d\out" --public-output-dir "$d\public"
```

این فرمان فقط وضعیت سازگاری/preview را می‌خواند؛ هیچ فرمان فعالی که حساب جاری را خرید بزند ارائه یا اجرا نشد. نتیجهٔ واقعی همین preview در `evidence/preview.paper-account-check.json`: دو مانع NSCStart/LastPossibleDeven سر جای خود، `public_calendar → no_new_session` با `calendar_ready=true`، شمارش ۰ (نامعلوم نیست)، برچسب نمایش سیاست در خروجی، hash حساب `7c6fa7f1…` بدون تغییر، آشتی نقد برقرار.

## پرچم‌ها و hashها

- `existing_account_modified=false` — حساب: قبل/بعد `7c6fa7f17f51fc93c8d3d439acfa52fbbbcc0b400653f585383f5201f0bb21b3`
- `official_ledger_modified=false` — قواعد 1.2.0: `ab31c9275fcdc96f787b91de1c8ec314cf32fedb5b6249aa17911bad90ec5646`؛ قرارداد قفل‌شده: `8b08cace7b64ee135ac862b6b9afd02242ba91cec24f8d6134b1d9b6c623c1c8`؛ O00: `3622b331798920d4…`؛ manifest شواهد کاندید: `5eb1ed64b0e28f7e…` (جزئیات در result.json)
- `model_contract_changed=false`؛ `.gitignore` فقط exceptionهای محدود TF-02 گرفت
- توکن درخواست/دریافت نشد؛ هیچ مقدار توکن در کد، گزارش یا Git نیست؛ `environ` در collector و adapter وجود ندارد (آزمون‌شده)

## مصرف‌کنندگان همچنان مسدود / غیرمجاز در این نسخه

admission فروش و timing PIT کدال (`SALES_PIT_TIMING_CAPABILITY_NOT_GRANTED_PUBLIC_PROFILE`)، تقویم رسمی آینده و O00 (تغییری نکردند)، cadence رسمی ۶۳جلسه‌ای، فعال‌سازی حساب جاری و مهاجرت (TF-03).

## محدودیت‌های صریح

- سیاست `public-paper-v1` پیشنهاد آزمایشی است و روی حساب جاری فعال نشده.
- دو شاخص از یک زیرساخت‌اند؛ `completeness_certified=false` برقرار است و فرض پایان جلسه گواه رسمی نیست.
- freshness ۶ساعته و تلورانس ۵دقیقه‌ای فرض عملیاتی نسخه‌داراند، نه قانون بورس.
- cross-check عمومی فعلی فقط ۱ نماد واجد شاهد هویت دارد؛ ادعای ۲۵۴ شاهد هم‌بازار وجود ندارد.
- اجرای کامل چرخهٔ تولید، scheduler و مسیرهای نوشتن عمومی در این مأموریت اجرا نشد؛ entrypointها با subprocess/mocks و خروجی موقت آزموده شدند.

پس از تحویل برای بازبینی TF-02 متوقف می‌شوم؛ اجرای عملیاتی TF-03 (حساب آزمایشی کامل + آماده‌سازی شروع) فقط پس از بازبینی.
