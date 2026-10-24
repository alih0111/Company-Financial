# گزارش تحویل TF-01A — اصلاح محدود نقص‌های اثبات‌شدهٔ بازبینی TF-01

تاریخ: 2026-10-24 (ساعت محلی تهران) · مخزن: `D:/RFA/Company-Financial` · دامنه: فقط collector/evaluator تقویم عمومی، تست‌های آن، مستند و استثناهای باریک Git. حساب جاری، قواعد pinشده، تصمیم/سفارش موجود، P1/P3، O00، DB، scheduler و اسکریپت‌های مصرف‌کننده دست‌نخورده. توکنی دریافت یا درخواست نشد. پس از این تحویل متوقف می‌شوم؛ TF-02 شروع نشده است.

## ۱. اعلام وضعیت پنج بخش

| بخش | وضعیت | شاهد آزمونی | شاهد probe |
|---|---|---|---|
| بلاک ۱ — هویت و وضعیت خطا | **PASS** | `test_candidate_payload_missing_rejected`, `test_candidate_wrong_inscode_rejected`, `test_single_source_failure_only_last_possible`, `test_invalid_last_possible_only_is_not_a_hidden_success`, `test_invalid_rows_rejected_and_identical_duplicates_deduped` (شناسهٔ duplicate)، `test_policy_validation_rejects_broken_contracts` | caseهای `candidate_payload_missing`، `candidate_wrong_inscode`، `completion_source_network_failure` در `evidence/reproduce_fixed.results.json` |
| بلاک ۲ — پوشش و معنای تکمیل | **PASS** (با محدودیت مستند: معنای اجزای LastPossibleDeven با شواهد عمومی قابل احراز نبود → `COMPLETION_UNVERIFIED` + `assumed_completion` نام‌دار) | `test_empty_secondary_is_insufficient_and_single_source_days_not_confirmed`, `test_secondary_missing_decision_anchor_is_insufficient`, `test_future_watermark_rejected`, `test_watermark_gates_completion_permission`, `test_agreeing_indices_yield_corroborated_public_sorted_set` (بلوک coverage و سه‌مفهومی) | `empty_secondary_before_decision`، هر دو case anchor |
| بلاک ۳ — cross-check معتبر و گزارش نامزد | **PASS** (با کاهش صادقانهٔ دامنه: فقط ۱ نماد واجد شرایط) | `test_candidate_traded_all_sessions_reports_no_missing_trade`, `test_candidate_one_no_trade_day`, `test_candidate_not_in_archive_is_unknown_not_no_trade`, `test_foreign_market_etf_and_unclassified_symbols_are_not_witnesses`, `test_corrupt_daily_rows_are_counted_or_skipped`, `test_cross_check_not_evaluated_when_index_quality_unusable` | `candidate_traded_all_sessions`، `foreign_market_non_equity_archive_not_filtered` |
| بلاک ۴ — بازپخش واقعی از شواهد pinشده | **PASS** | `test_cli_replay_is_pinned_and_needs_no_current_state` (حساب/آرشیو ناموجود + sentinel؛ برابری کامل معنایی؛ دست‌کاری raw → `REPLAY_RAW_CHANGED`؛ نسخهٔ parser ناسازگار → رد یا برچسب `re-evaluated`)، `test_offline_replay_from_saved_manifest_matches_and_detects_tampering` (حفظ provenance)، `test_manifest_write_is_exclusive_and_hash_matches_file` | `offline_drops_source_provenance` (۵/۵ حفظ شد)، `offline_cli_depends_on_current_account` (sentinel اجرا نشد) |
| بستهٔ تحویل/آزمون‌ها | **PASS** | scoped: **۸۷ passed** (۳۰ آزمون تقویم + ۵۹ مبنا)، بدون شبکه در pytest؛ `py_compile` هر دو فایل Python موفق | — |

## ۲. سه مفهوم جدا — خروجی معنایی جدید (schema v2)

- **کیفیت مشاهدهٔ تقویم** (`quality`): وضعیت شواهد تاریخِ دو شاخص — `CORROBORATED_PUBLIC` فقط با توافق دو شاخصِ دارای anchor تصمیم.
- **تأیید تکمیل** (`completion` + `readiness.completion_officially_confirmed`): همیشه `COMPLETION_UNVERIFIED` در این نسخه. توافق دو جزء LastPossibleDeven فقط یک مشاهده است و به `assumed_completion` با `policy_version=public-calendar-policy@1.1` می‌رود — فرض عملیاتیِ نام‌دار، نه تأیید رسمی. هیچ شاهد عمومی قابل ارجاعی برای معنای اجزا پیدا نشد؛ پایان ساعت معمول بازار هم هرگز شاهد تکمیل نیست.
- **اجازهٔ fill** (`readiness.fill_capable`): همیشه `false` در TF-01A؛ هیچ مصرف‌کننده‌ای وصل نشد. `readiness.note` صریحاً می‌گوید هیچ consumer آینده نباید صرفاً از quality مجوز بگیرد.

نتایج zندهٔ نهایی این را نشان می‌دهد: `quality=CORROBORATED_PUBLIC`، `readiness=USABLE_COMPLETION_UNVERIFIED`، `assumed_completion=20261021`، `sessions_after_decision=NO_NEW_SESSION (count=0)`.

## ۳. تغییرات schema و probe تطبیقی

schema از ۱ به ۲ ارتقا یافت (parser `…@1.1.0`): `completion_confirmed` جلسات → `corroborated` + `within_assumed_completion`؛ `COMPLETION_CORROBORATED_THROUGH_WATERMARK` حذف شد؛ `source_health`، `readiness`، coverage هر منبع + union + intersection + پنجره‌ها، `pre_window_history_start_difference` (برچسب درست «تفاوت شروع تاریخچه»، غیرمسدودکننده) جایگزین نام قبلی؛ شمارش جلسه در حالت نامعلوم `null`. probe بازبینی دست‌نخورده ماند و نسخهٔ تطبیقی جدید در `evidence/reproduce_fixed.py` + `reproduce_fixed.results.json` هر ۱۰ case را روی کد اصلاح‌شده اجرا می‌کند — همه مطابق رفتار صحیح (از جمله `accepted_as_corroborated=false` برای هر سه case هویت/منبع، صفر جلسهٔ تک‌منبعی «تأییدشده»، و برابری کامل بازپخش).

## ۴. اجراهای واقعی (زنده و بازپخش)

| فرمان | نتیجه |
|---|---|
| `pytest …test_public_market_calendar.py` | ۳۰ passed |
| `pytest …test_public_market_calendar.py …test_paper_account_atomic.py …test_paper_cycle_http.py` | **۸۷ passed** |
| اجرای زندهٔ ۱: `…acquire_public_market_calendar.py --window-start 20261022` | `manifest.20261023T210206670875Z` — خطای گذرای شبکه در شاخص ثانویه → `FETCH_FAILED` صریح (رفتار درست بلاک ۱). این اجرا دو نقص آبشاری باقی‌مانده را آشکار کرد: شاهدهای سهام بر مجموعهٔ جلساتِ خالی، و پاک‌شدن error_code منبع خراب در بازپخش؛ هر دو اصلاح و با تست قفل شدند (`test_cross_check_not_evaluated_when_index_quality_unusable`, `test_replay_preserves_failed_source_error_code`). |
| اجرای زندهٔ ۲ (نهایی): همان فرمان | `manifest.20261023T210632330575Z` — sha256=`b8cb3a4c94258b8abeec5ec7de46d199fe49edf05df7c473ff4830595be1546c` · CORROBORATED_PUBLIC · zero conflict · cross-check: eligible=1 (غاذر با evidence زندهٔ InstrumentInfo)، skipped=253 (`unclassified_no_identity_evidence`) · self-replay: برابری کامل همهٔ فیلدها از جمله `problems` |
| بازپخش CLI: `… --from-manifest …manifest.20261023T210632330575Z.json` | `manifest.20261023T210713634854Z` — mode=replay، clock pinشده، برابری کامل معنایی با منبع |

live و fixture جدا هستند؛ اجرای زندهٔ محدود فقط ۵ GET عمومی بدون Authorization است. cross-check سهام صرفاً offline از آرشیو محلی با هش تأییدشده انجام شد و ۲۵۴ درخواست زنده ساخته نشد.

## ۵. توضیح اختلاف هش‌های تحویل TF-01 (دست‌نخورده نگه داشته شد)

جداول `REPORT.fa.md` قبلی هش چاپی stdout را نقل می‌کرد که روی رشتهٔ JSON با `\n` محاسبه شده بود؛ اما `Path.write_text` در ویندوز newline را به `\r\n` ترجمه می‌کند، پس بایت‌های فایل روی دیسک (و `result.json` که هش فایل را داشت) با آن عدد فرق دارد (`a788836f…`/`c44587a2…` مقابل `0e38c0cc…`/`7db9f4cf…`). result.json با دیسک سازگار بود. در TF-01A نوشتن manifest با `newline="\n"` و open انحصاری انجام و هش از بایت‌های نهایی فایل گرفته می‌شود — stdout، pointer و دیسک حالا همیشه برابرند (آزمون `test_manifest_write_is_exclusive_and_hash_matches_file`). فایل‌های تحویل قبلی تغییر داده نشدند. `.gitignore` هم اکنون در artifact-manifest این تحویل با هش ثبت شده است.

## ۶. سه پرچم با فهرست/هش فایل‌های دفتر

`existing_account_modified=false`، `official_ledger_modified=false`، `model_contract_changed=false`. این‌بار به‌جای استنتاج از سه فایل، خودِ فایل‌های دفتر فهرست و هش شدند (قبل = بعد، در `result.json` → `flags.ledger_files_before_equal_after`): حساب جاری، `execution_rules_v1_2_0.json`، قرارداد قفل‌شدهٔ v12_28، `analysis_contract.locked.json` منبع v12_27، قرارداد global منبع v12_23 و `o00_session_calendar.csv`. فایل حساب فقط در حالت live و فقط‌خواندنی خوانده شد؛ مسیر `--from-manifest` پیش از هر دسترسی به حساب از live جدا شد.

## ۷. فایل‌های تحویل

سورس (`acquire_public_market_calendar.py`)، تست (`test_public_market_calendar.py`)، `.gitignore`، این گزارش، `result.json` (artifact-manifest کامل با اندازه/SHA-256 بایت‌های نهایی؛ خود result.json را هش نمی‌کند) و شواهد: سه manifest اجراها، `reproduce_fixed.py` و `reproduce_fixed.results.json`. rawهای gzip هر اجرا در `ranking_research/output/public_market_calendar_tf01/raw/` با هشِ بایت‌های غیرفشرده در همان manifestها.

## ۸. توقف

TF-01A اینجا متوقف می‌شود. اتصال adapter مشترک (TF-02)، پذیرش در حساب عملیاتی و مسیر فروش، منتظر بازبینی همین تحویل و تصمیم صریح است. خروجی «شنبه جلسهٔ جدید ندارد» صرفِ نبود دادهٔ تکمیل‌شدهٔ پس از تصمیم است؛ نه مجوز fill و نه شکست.
